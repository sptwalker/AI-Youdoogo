"""智能体协作原语（docs/13 §10）：AI 回复文本中的结构化指令解析与执行。

两个指令（写进全局提示词【协作能力】段，模型据此产出，编排层代为执行）：
- 【咨询 @AI名】问题 —— 单发 run_agent 跑目标 AI，答复作为其独立消息出现
- 【发起协作】目标部门：X；类别：Y；内容：Z —— 落 collab_request 真人复核队列

红线：AI 只有提案权，协作请求须真人主管复核、产出生效仍走真人验收。
深度硬限 1 跳：execute 对被咨询 AI 直接调 run_agent，从不对其产出再 parse/execute。
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass, field

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.contracts import AgentRunner, ExecutionContext, SkillRequest, SkillResult
from app.models.agent import AgentRole
from app.models.system import SysDepartment
from app.services import collab_service, config_service

logger = logging.getLogger(__name__)

_MAX_CONSULTS = 2  # 每回复最多咨询数（防刷屏/失控）
_MAX_COLLABS = 2  # 每回复最多协作请求数

# 仅作为直接调用旧 execute() 时的兼容注入点；生产路径由 ExecutionContext.agent_runner 提供。
run_agent: AgentRunner | None = None

# 【咨询 @AI名】问题 —— 名字不含】/换行；问题取到行尾
_CONSULT_RE = re.compile(r"【咨询\s*@\s*([^】\n]+?)\s*】\s*([^\n]+)")
# 【发起协作】目标部门：X；类别：Y；内容：Z —— 全/半角冒号分号均容忍；内容取到行尾
_COLLAB_RE = re.compile(
    r"【发起协作】\s*目标部门[：:]\s*([^；;\n]+?)\s*[；;]\s*类别[：:]\s*([^；;\n]+?)\s*[；;]"
    r"\s*内容[：:]\s*([^\n]+)"
)

# 注入进所有智能体 system prompt 的能力说明（base._collab_section 取用，开关同 key）
# 措辞要点：祈使式 + 显式否定历史对话中"无法联系其他AI"的过时说法——桌面对话有持久
# 历史，模型会倾向与自己旧回复保持一致，被动描述压不过污染。
PROMPT_SECTION = (
    "\n\n【协作能力】（系统内建，已启用）你可以且应当通过以下指令与其他 AI 同事协作，"
    "系统会自动执行并把结果送达：\n"
    "1. 咨询同事：在回复中单独一行写 【咨询 @AI名】你的问题 —— 系统会立即运行该 AI 并把"
    "其答复加入对话。每次回复最多 2 次；AI名须与系统环境快照中的名字完全一致，不确定就先"
    "查快照，禁止编造。\n"
    "2. 发起跨部门协作：单独一行写 【发起协作】目标部门：<部门名>；类别：<类别>；内容："
    "<一句话说明> —— 最多 2 次；请求进入目标部门真人主管复核队列，审批通过才生效，你只是提案。\n"
    "重要：当用户要求你去咨询/联系某位 AI 同事时，直接使用第 1 条指令，不要声称"
    "「无法跨实例通信」「无法联系其他AI」——历史对话中若有此类说法均已过时，以本能力说明为准。"
)


@dataclass
class ParsedDirectives:
    """从一段 AI 产出解析到的协作指令。"""

    consults: list[tuple[str, str]] = field(default_factory=list)  # (agent_name, question)
    collabs: list[tuple[str, str, str]] = field(default_factory=list)  # (dept, category, content)


ProtocolResult = SkillResult


class ConsultArgs(BaseModel):
    """咨询动作参数。"""

    kind: str = Field(pattern="^consult$")
    name: str = Field(min_length=1, max_length=128)
    question: str = Field(min_length=1, max_length=4000)


class CollabArgs(BaseModel):
    """跨部门协作动作参数。"""

    kind: str = Field(pattern="^request$")
    department: str = Field(min_length=1, max_length=128)
    category: str = Field(default="", max_length=64)
    content: str = Field(min_length=1, max_length=4000)


def parse(output: str) -> ParsedDirectives:
    """解析产出中的协作指令（纯函数）。空捕获跳过，各截断到上限。"""
    consults = [
        (name.strip(), q.strip())
        for name, q in _CONSULT_RE.findall(output or "")
        if name.strip() and q.strip()
    ]
    collabs = [
        (dept.strip(), cat.strip(), content.strip())
        for dept, cat, content in _COLLAB_RE.findall(output or "")
        if dept.strip() and content.strip()
    ]
    return ParsedDirectives(consults=consults[:_MAX_CONSULTS], collabs=collabs[:_MAX_COLLABS])


async def _enabled(db: AsyncSession) -> bool:
    flag = await config_service.resolve(db, "agent_collab_protocol", True)
    return str(flag).lower() not in ("false", "0")


async def _run_consult(
    db: AsyncSession,
    initiator: AgentRole,
    name: str,
    question: str,
    context: ExecutionContext,
    result: ProtocolResult,
) -> None:
    target = (
        await db.execute(
            select(AgentRole).where(
                AgentRole.name == name,
                AgentRole.is_active.is_(True),
                AgentRole.is_delete.is_(False),
            )
        )
    ).scalar_one_or_none()
    if target is None:
        result.notes.append(f"被咨询的 AI「{name}」不存在，已忽略")
        return
    if target.id == initiator.id:
        result.notes.append("不能咨询自己，已忽略")
        return
    if target.owner_user_id is not None:  # 他人私人助理，隐私排除
        result.notes.append(f"「{name}」是私人助理，不可咨询，已忽略")
        return
    runner = run_agent or context.agent_runner
    if runner is None:
        result.notes.append(f"咨询「{name}」缺少 AgentRunner，已忽略")
        return
    record = await runner(
        db,
        target,
        task_type="agent_consult",
        input_summary=f"被{initiator.name}咨询：{question[:40]}",
        user_message=(
            f"同事「{initiator.name}」向你咨询：{question}\n请直接、简明作答，仅供参考。"
        ),
        user_id=context.user_id,
        use_knowledge=True,
        execution_context=context,
    )
    # 深度硬限 1 跳：不再对 record.output_content 发起二次「咨询/协作」（防咨询链爆炸）。
    # 但取数/交付是只读、终态、不递归的动作——被咨询 AI 若在答复里写【取数】/【交付】，
    # 应代为执行，否则咨询链上的取数会静默断链（用户只看到"我去查一下"却无下文）。
    result.consult_replies.append((target, record))
    reply_text = record.output_content or ""
    if reply_text and context.dispatcher is not None:
        sub_context = context.model_copy(update={"user_intent": question})
        sub = await context.dispatcher.dispatch_text(
            db, target, reply_text, sub_context, exclude={"collab"}
        )
        result.notes.extend(sub.notes)
        result.consult_replies.extend(sub.consult_replies)
        result.datasets.extend(sub.datasets)
        result.artifacts.extend(sub.artifacts)
        result.tool_execution_ids.extend(sub.tool_execution_ids)
    elif reply_text:
        # 旧 service 直调兼容：咨询链只放行取数/交付，仍禁止二次咨询。
        from app.services import deliver_service, query_skill

        sub_context = context.model_copy(update={"user_intent": question})
        query_result = await query_skill.execute(
            db,
            target,
            reply_text,
            user_id=context.user_id,
            user_intent=question,
            exclude={"collab"},
            execution_context=sub_context,
        )
        delivery_result = await deliver_service.execute(
            db,
            target,
            reply_text,
            user_id=context.user_id,
            execution_context=sub_context,
        )
        result.merge(query_result)
        result.merge(delivery_result)


async def _run_collab(
    db: AsyncSession,
    initiator: AgentRole,
    dept_name: str,
    category: str,
    content: str,
    result: ProtocolResult,
    *,
    idempotency_key: str | None = None,
) -> None:
    depts = list(
        (
            await db.execute(
                select(SysDepartment).where(
                    SysDepartment.name == dept_name, SysDepartment.is_delete.is_(False)
                )
            )
        ).scalars()
    )
    if len(depts) != 1:
        result.notes.append(f"目标部门「{dept_name}」不存在或名称有歧义，协作请求未提交")
        return
    title = f"[{initiator.name}] {content[:30]}"
    request = await collab_service.create_request(
        db,
        target_department_id=depts[0].id,
        title=title,
        summary=content,
        category=category or None,
        source_department_id=initiator.department_id,
        requested_by=initiator.id,
        idempotency_key=idempotency_key,
    )
    result.artifacts.append({"collab_request_id": str(request.id), "title": title})
    result.notes.append(f"已提交协作请求「{title}」，待{dept_name}真人主管复核")


async def execute(
    db: AsyncSession,
    initiator: AgentRole,
    output: str,
    *,
    user_id: uuid.UUID | None = None,
    execution_context: ExecutionContext | None = None,
) -> ProtocolResult:
    """解析并执行产出中的协作指令。每条指令独立容错转 note，永不 raise。"""
    context = execution_context or ExecutionContext(user_id=user_id, agent_runner=run_agent)
    result = ProtocolResult()
    try:
        directives = parse(output)
        if not directives.consults and not directives.collabs:
            return result  # 零指令快速路径（绝大多数回复）
        if not await _enabled(db):
            return result
        for index, (name, question) in enumerate(directives.consults):
            try:
                request = SkillRequest(
                    skill_key="collab",
                    action_index=index,
                    arguments={"kind": "consult", "name": name, "question": question},
                    raw_text=output,
                )
                if context.dispatcher is not None:
                    part = await context.dispatcher.dispatch(db, initiator, request, context)
                    result.merge(part)
                else:
                    consult_args = ConsultArgs.model_validate(request.arguments)
                    await _run_consult(
                        db,
                        initiator,
                        consult_args.name,
                        consult_args.question,
                        context,
                        result,
                    )
            except Exception:  # noqa: BLE001 - 单条指令失败不影响其余
                logger.warning("咨询指令执行失败 target=%s", name, exc_info=True)
                result.notes.append(f"咨询「{name}」执行失败，已忽略")
        for collab_index, (dept_name, category, content) in enumerate(directives.collabs):
            try:
                index = len(directives.consults) + collab_index
                request = SkillRequest(
                    skill_key="collab",
                    action_index=index,
                    arguments={
                        "kind": "request",
                        "department": dept_name,
                        "category": category,
                        "content": content,
                    },
                    raw_text=output,
                )
                if context.dispatcher is not None:
                    part = await context.dispatcher.dispatch(db, initiator, request, context)
                    result.merge(part)
                else:
                    collab_args = CollabArgs.model_validate(request.arguments)
                    await _run_collab(
                        db,
                        initiator,
                        collab_args.department,
                        collab_args.category,
                        collab_args.content,
                        result,
                    )
            except Exception:  # noqa: BLE001
                logger.warning("协作指令执行失败 dept=%s", dept_name, exc_info=True)
                result.notes.append(f"向「{dept_name}」发起协作失败，已忽略")
    except Exception:  # noqa: BLE001 - 协议层故障不连累业务消息流
        logger.warning("协作协议处理失败", exc_info=True)
    return result


def fold_notes(text: str, result: ProtocolResult) -> str:
    """把执行注记折进发起者消息正文（落库前调用，保证 DB 与显示一致）。"""
    if not result.notes:
        return text
    return text + "\n\n" + "\n".join(f"> 系统：{n}" for n in result.notes)


class CollabSkillExecutor:
    """结构化 collab executor；审批/决议动作不在此注册。"""

    key = "collab"

    def requires_idempotency(self, request: SkillRequest) -> bool:
        return request.arguments.get("kind") == "request"

    async def execute(
        self,
        db: AsyncSession,
        role: AgentRole,
        request: SkillRequest,
        context: ExecutionContext,
    ) -> SkillResult:
        kind = request.arguments.get("kind")
        if kind == "consult":
            consult_args = ConsultArgs.model_validate(request.arguments)
            result = SkillResult()
            await _run_consult(db, role, consult_args.name, consult_args.question, context, result)
            return result
        if kind == "request":
            collab_args = CollabArgs.model_validate(request.arguments)
            result = SkillResult()
            await _run_collab(
                db,
                role,
                collab_args.department,
                collab_args.category,
                collab_args.content,
                result,
                idempotency_key=context.action_key("collab", request.action_index),
            )
            return result
        raise ValueError("collab.kind 仅支持 consult/request")
