"""Agent protocol and typed capability adapter for Collaboration Requests."""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.contracts import AgentRunner, ExecutionContext, SkillRequest, SkillResult
from app.contexts.business.collaboration_requests.application.contracts import (
    CollaborationRequestResult,
)
from app.contexts.business.collaboration_requests.entrypoints import operations
from app.models.agent import AgentRole
from app.models.system import SysDepartment

logger = logging.getLogger(__name__)

_MAX_CONSULTS = 2
_MAX_COLLABS = 2
_CONSULT_RE = re.compile(r"【咨询\s*@\s*([^】\n]+?)\s*】\s*([^\n]+)")
_COLLAB_RE = re.compile(
    r"【发起协作】\s*目标部门[：:]\s*([^；;\n]+?)\s*[；;]\s*类别[：:]\s*"
    r"([^；;\n]+?)\s*[；;]\s*内容[：:]\s*([^\n]+)"
)

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
    consults: list[tuple[str, str]] = field(default_factory=list)
    collabs: list[tuple[str, str, str]] = field(default_factory=list)


ProtocolResult = SkillResult


class ConsultArgs(BaseModel):
    kind: str = Field(pattern="^consult$")
    name: str = Field(min_length=1, max_length=128)
    question: str = Field(min_length=1, max_length=4000)


class CollabArgs(BaseModel):
    kind: str = Field(pattern="^request$")
    department: str = Field(min_length=1, max_length=128)
    category: str = Field(default="", max_length=64)
    content: str = Field(min_length=1, max_length=4000)


class FeatureFlagResolver(Protocol):
    async def __call__(
        self,
        db: AsyncSession,
        key: str,
        default: Any = None,
    ) -> Any: ...


RunnerProvider = Callable[[], AgentRunner | None]
RequestCreator = Callable[..., Awaitable[CollaborationRequestResult]]
FallbackExecutor = Callable[
    [AsyncSession, AgentRole, str, ExecutionContext, str],
    Awaitable[SkillResult],
]
ExecutorFactory = Callable[[], "CollabSkillExecutor"]


def parse(output: str) -> ParsedDirectives:
    consults = [
        (name.strip(), question.strip())
        for name, question in _CONSULT_RE.findall(output or "")
        if name.strip() and question.strip()
    ]
    collabs = [
        (department.strip(), category.strip(), content.strip())
        for department, category, content in _COLLAB_RE.findall(output or "")
        if department.strip() and content.strip()
    ]
    return ParsedDirectives(
        consults=consults[:_MAX_CONSULTS],
        collabs=collabs[:_MAX_COLLABS],
    )


async def _enabled(
    db: AsyncSession,
    resolver: FeatureFlagResolver | None,
) -> bool:
    if resolver is None:
        return True
    flag = await resolver(db, "agent_collab_protocol", True)
    return str(flag).lower() not in ("false", "0")


class CollabSkillExecutor:
    key = "collab"

    def __init__(
        self,
        *,
        runner_provider: RunnerProvider | None = None,
        request_creator: RequestCreator = operations.create_request,
        fallback_executor: FallbackExecutor | None = None,
    ) -> None:
        self._runner_provider = runner_provider
        self._request_creator = request_creator
        self._fallback_executor = fallback_executor

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
            await self._run_consult(
                db,
                role,
                consult_args.name,
                consult_args.question,
                context,
                result,
            )
            return result
        if kind == "request":
            collab_args = CollabArgs.model_validate(request.arguments)
            result = SkillResult()
            await self._run_collab(
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

    async def _run_consult(
        self,
        db: AsyncSession,
        initiator: AgentRole,
        name: str,
        question: str,
        context: ExecutionContext,
        result: SkillResult,
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
        if target.owner_user_id is not None:
            result.notes.append(f"「{name}」是私人助理，不可咨询，已忽略")
            return
        runner = (
            self._runner_provider() if self._runner_provider is not None else None
        ) or context.agent_runner
        if runner is None:
            result.notes.append(f"咨询「{name}」缺少 AgentRunner，已忽略")
            return
        active_context = context.model_copy(update={"agent_runner": runner})
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
            execution_context=active_context,
        )
        result.consult_replies.append((target, record))
        reply_text = record.output_content or ""
        if not reply_text:
            return
        excluded = set(active_context.excluded_skills) | {"collab"}
        sub_context = active_context.model_copy(
            update={
                "user_intent": question,
                "excluded_skills": frozenset(excluded),
            }
        )
        if active_context.dispatcher is not None:
            result.merge(
                await active_context.dispatcher.dispatch_text(
                    db,
                    target,
                    reply_text,
                    sub_context,
                    exclude=excluded,
                )
            )
            return
        if self._fallback_executor is not None:
            result.merge(
                await self._fallback_executor(
                    db,
                    target,
                    reply_text,
                    sub_context,
                    question,
                )
            )

    async def _run_collab(
        self,
        db: AsyncSession,
        initiator: AgentRole,
        department_name: str,
        category: str,
        content: str,
        result: SkillResult,
        *,
        idempotency_key: str | None = None,
    ) -> None:
        departments = list(
            (
                await db.execute(
                    select(SysDepartment).where(
                        SysDepartment.name == department_name,
                        SysDepartment.is_delete.is_(False),
                    )
                )
            ).scalars()
        )
        if len(departments) != 1:
            result.notes.append(
                f"目标部门「{department_name}」不存在或名称有歧义，协作请求未提交"
            )
            return
        title = f"[{initiator.name}] {content[:30]}"
        request = await self._request_creator(
            db,
            target_department_id=departments[0].id,
            title=title,
            summary=content,
            category=category or None,
            source_department_id=initiator.department_id,
            requested_by=initiator.id,
            idempotency_key=idempotency_key,
        )
        result.artifacts.append(
            {"collab_request_id": str(request.id), "title": title}
        )
        result.notes.append(
            f"已提交协作请求「{title}」，待{department_name}真人主管复核"
        )


async def execute(
    db: AsyncSession,
    initiator: AgentRole,
    output: str,
    *,
    user_id: uuid.UUID | None = None,
    exclude: set[str] | None = None,
    execution_context: ExecutionContext | None = None,
    runner_provider: RunnerProvider | None = None,
    feature_flag_resolver: FeatureFlagResolver | None = None,
    executor_factory: ExecutorFactory = CollabSkillExecutor,
) -> SkillResult:
    """Parse and execute collaboration directives without breaking message flow."""
    context = execution_context or ExecutionContext(user_id=user_id)
    updates: dict[str, Any] = {}
    if context.user_id is None and user_id is not None:
        updates["user_id"] = user_id
    runner = runner_provider() if runner_provider is not None else None
    if runner is not None:
        updates["agent_runner"] = runner
    requested_exclusions = frozenset(exclude or ())
    if requested_exclusions:
        updates["excluded_skills"] = context.excluded_skills | requested_exclusions
    if updates:
        context = context.model_copy(update=updates)
    result = SkillResult()
    try:
        directives = parse(output)
        if not directives.consults and not directives.collabs:
            return result
        if not await _enabled(db, feature_flag_resolver):
            return result
        for index, (name, question) in enumerate(directives.consults):
            try:
                request = SkillRequest(
                    skill_key="collab",
                    action_index=index,
                    arguments={
                        "kind": "consult",
                        "name": name,
                        "question": question,
                    },
                    raw_text=output,
                )
                part = (
                    await context.dispatcher.dispatch(db, initiator, request, context)
                    if context.dispatcher is not None
                    else await executor_factory().execute(db, initiator, request, context)
                )
                result.merge(part)
            except Exception:  # noqa: BLE001 - isolate each directive
                logger.warning("咨询指令执行失败 target=%s", name, exc_info=True)
                result.notes.append(f"咨询「{name}」执行失败，已忽略")
        for collab_index, (department, category, content) in enumerate(
            directives.collabs
        ):
            try:
                action_index = len(directives.consults) + collab_index
                request = SkillRequest(
                    skill_key="collab",
                    action_index=action_index,
                    arguments={
                        "kind": "request",
                        "department": department,
                        "category": category,
                        "content": content,
                    },
                    raw_text=output,
                )
                part = (
                    await context.dispatcher.dispatch(db, initiator, request, context)
                    if context.dispatcher is not None
                    else await executor_factory().execute(db, initiator, request, context)
                )
                result.merge(part)
            except Exception:  # noqa: BLE001 - isolate each directive
                logger.warning("协作指令执行失败 dept=%s", department, exc_info=True)
                result.notes.append(f"向「{department}」发起协作失败，已忽略")
    except Exception:  # noqa: BLE001 - protocol failure is never fatal
        logger.warning("协作协议处理失败", exc_info=True)
    return result


def fold_notes(text: str, result: SkillResult) -> str:
    if not result.notes:
        return text
    return text + "\n\n" + "\n".join(f"> 系统：{note}" for note in result.notes)


__all__ = [
    "CollabArgs",
    "CollabSkillExecutor",
    "ConsultArgs",
    "PROMPT_SECTION",
    "ParsedDirectives",
    "ProtocolResult",
    "execute",
    "fold_notes",
    "parse",
]
