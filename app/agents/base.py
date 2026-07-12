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

logger = logging.getLogger(__name__)

# agent_role.model_role（粗粒度档位）→ app/llm/roles.py 的 LLM 角色键
_LLM_ROLE_BY_TIER: dict[str, str] = {"daily": "default", "reasoning": "meeting_expert"}


async def get_agent_role(db: AsyncSession, name: str) -> AgentRole | None:
    """按角色名取启用中的智能体角色（name 为 docs/03 定义的唯一业务键）。"""
    stmt = select(AgentRole).where(
        AgentRole.name == name,
        AgentRole.is_active.is_(True),
        AgentRole.is_delete.is_(False),
    )
    return (await db.execute(stmt)).scalar_one_or_none()


def _as_text(msg: AIMessage) -> str:
    """把模型返回内容规整为字符串（多数为 str，少数模型返回分段列表）。"""
    content = msg.content
    return content if isinstance(content, str) else str(content)


async def run_agent(
    db: AsyncSession,
    role: AgentRole,
    *,
    task_type: str,
    input_summary: str,
    user_message: str,
    user_id: uuid.UUID | None = None,
) -> AgentTaskRecord:
    """执行一次智能体任务并落一条留痕记录。

    LLM 调用失败（含无可用密钥）转为 status=failed 的记录返回，不向上抛，
    保证「每次AI操作都有痕迹」且调用方拿到可展示的失败原因。
    """
    llm_role = _LLM_ROLE_BY_TIER.get(role.model_role, "default")
    t0 = time.monotonic()
    output: str | None = None
    model_used: str | None = None
    status = "success"
    error_msg: str | None = None
    usage: tuple[int, int, int] = (0, 0, 0)
    try:
        llm = get_llm_for_role(llm_role, temperature=0.3)
        reply = await llm.ainvoke(
            [SystemMessage(content=role.prompt_template), HumanMessage(content=user_message)]
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
