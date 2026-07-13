"""智能体核心：加载角色 → 调用模型 → 全程留痕（docs/04 红线：AI操作必须留痕）。

run_agent 是所有部门智能体共用的执行外壳：成功/失败都写一条 agent_task_record，
失败不抛给上层（转为 status=failed 的留痕记录返回），符合「所有AI输出可编辑/驳回/终止」。
"""

from __future__ import annotations

import logging
import time
import uuid

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm import get_llm_for_role
from app.llm.usage import extract_usage, record_usage
from app.models.agent import AgentRole, AgentTaskRecord
from app.services import config_service

logger = logging.getLogger(__name__)

# agent_role.model_role（粗粒度档位）→ app/llm/roles.py 的 LLM 角色键
_LLM_ROLE_BY_TIER: dict[str, str] = {"daily": "default", "reasoning": "meeting_expert"}

# 全局红线不变量（提示词分层前缀）；可经 sys_config('agent_global_prompt') 覆盖，一处改全局
_DEFAULT_GLOBAL_PROMPT = (
    "【公司红线】你是创想悦动公司的 AI 顾问/助理，仅有建议、分析、辅助执行权；"
    "涉及资金、人事、项目、重大业务调整的决议必须由真人确认才生效，你的产出一律为草稿/参考。"
    "只依据已知事实作答、禁止编造；引用资料须可溯源；保持专业、简明的公司口吻。"
)


async def get_agent_role(db: AsyncSession, name: str) -> AgentRole | None:
    """按角色名取启用中的智能体角色。"""
    stmt = select(AgentRole).where(
        AgentRole.name == name,
        AgentRole.is_active.is_(True),
        AgentRole.is_delete.is_(False),
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_agent_role_by_code(db: AsyncSession, code: str) -> AgentRole | None:
    """按稳定 code 取启用中的智能体（code 为种子键，不随显示名变，比 name 更可靠）。"""
    stmt = select(AgentRole).where(
        AgentRole.code == code,
        AgentRole.is_active.is_(True),
        AgentRole.is_delete.is_(False),
    )
    return (await db.execute(stmt)).scalar_one_or_none()


def _as_text(msg: AIMessage) -> str:
    """把模型返回内容规整为字符串（多数为 str，少数模型返回分段列表）。"""
    content = msg.content
    return content if isinstance(content, str) else str(content)


async def _inject_knowledge(db: AsyncSession, role: AgentRole, user_message: str) -> str:
    """按 AI 员工的部门可见范围检索知识库，把相关资料拼进消息前作【参考资料】。

    检索/embedding 任何失败都不阻断任务：记 warning、返回原消息。
    """
    try:
        from app.knowledge import retrieval
        from app.knowledge.scope import resolve_agent_visible_kb_ids

        kb_ids = await resolve_agent_visible_kb_ids(
            db, department_id=role.department_id, owner_agent_id=role.id
        )
        hits = await retrieval.search(db, user_message, top_k=5, visible_kb_ids=kb_ids)
        if not hits:
            return user_message
        materials = "\n\n".join(
            f"[{i + 1}] {h.chunk_text}（来源：{h.file_name}）" for i, h in enumerate(hits)
        )
        return (
            f"【参考资料】（来自你部门范围内的知识库，回答时可引用并标注来源）\n{materials}\n\n"
            f"【任务】\n{user_message}"
        )
    except Exception:  # noqa: BLE001 - 知识检索故障不阻断 AI 任务
        logger.warning("知识库检索注入失败，改为无资料执行 role=%s", role.name, exc_info=True)
        return user_message


async def run_agent(
    db: AsyncSession,
    role: AgentRole,
    *,
    task_type: str,
    input_summary: str,
    user_message: str,
    user_id: uuid.UUID | None = None,
    use_knowledge: bool = False,
) -> AgentTaskRecord:
    """执行一次智能体任务并落一条留痕记录。

    LLM 调用失败（含无可用密钥）转为 status=failed 的记录返回，不向上抛，
    保证「每次AI操作都有痕迹」且调用方拿到可展示的失败原因。

    use_knowledge=True 时，先按该 AI 员工的部门可见范围检索知识库，把相关资料注入
    提示词（开卷作答）；检索失败不阻断执行。AI 只能检索自己部门范围内的知识。
    """
    llm_role = _LLM_ROLE_BY_TIER.get(role.model_role, "default")
    # 提示词分层前缀先取（配置层故障不应连累 AI 执行，回退内置红线默认）
    try:
        global_prompt = await config_service.resolve(
            db, "agent_global_prompt", _DEFAULT_GLOBAL_PROMPT
        )
    except Exception:  # noqa: BLE001 - sys_config 不可用时用内置默认，不阻断 AI
        logger.warning("读取 agent_global_prompt 失败，回退内置默认", exc_info=True)
        global_prompt = _DEFAULT_GLOBAL_PROMPT
    # AI 员工按自身部门范围检索知识库并注入（检索故障不阻断任务）
    effective_message = user_message
    if use_knowledge:
        effective_message = await _inject_knowledge(db, role, user_message)
    t0 = time.monotonic()
    output: str | None = None
    model_used: str | None = None
    status = "success"
    error_msg: str | None = None
    usage: tuple[int, int, int] = (0, 0, 0)
    try:
        llm = get_llm_for_role(llm_role, temperature=0.3)
        # 提示词分层：全局红线不变量前缀 + 该角色特有段（docs/13 §4）
        system_content = f"{global_prompt}\n\n{role.prompt_template}"
        reply = await llm.ainvoke(
            [SystemMessage(content=system_content), HumanMessage(content=effective_message)]
        )
        output = _as_text(reply)
        # 实际命中模型（经降级链后）优先取响应元数据，缺失则记档位
        model_used = str(reply.response_metadata.get("model_name") or llm_role)
        usage = extract_usage(reply)
    except Exception as exc:  # noqa: BLE001 - 失败也要留痕，不阻断调用方
        status = "failed"
        error_msg = str(exc)
        logger.exception("智能体执行失败 role=%s task=%s", role.name, task_type)

    duration_ms = int((time.monotonic() - t0) * 1000)
    record = AgentTaskRecord(
        agent_role_id=role.id,
        task_type=task_type,
        input_summary=input_summary,
        output_content=output,
        model_used=model_used,
        status=status,
        error_msg=error_msg,
        duration_ms=duration_ms,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    await record_usage(
        db, role=llm_role, model=model_used,
        prompt_tokens=usage[0], completion_tokens=usage[1], total_tokens=usage[2],
        duration_ms=duration_ms, status=status, task_id=record.id, user_id=user_id,
    )
    return record
