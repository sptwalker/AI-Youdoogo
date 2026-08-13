"""Compose cross-context handlers for durable workflow outbox events."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.contracts import AgentRunner
from app.contexts.business.group_messaging.public import (
    DISBAND_ARCHIVE_EVENT,
    archive_disbanded_channel,
)
from app.contexts.business.task_management.contracts.tasks import (
    TASK_DECISION_RECORDED_V1,
)
from app.contexts.business.task_management.infrastructure.sqlalchemy_adapter import (
    SQLAlchemyTaskManagementAdapter,
    task_decision_from_payload,
)
from app.contexts.foundations.environment_projection import (
    public as environment_projection,
)
from app.contexts.foundations.environment_projection.contracts.source_change import (
    ENVIRONMENT_SOURCE_CHANGED_V1,
)
from app.contexts.foundations.environment_projection.infrastructure.source_change_handler import (
    handle_source_change,
)
from app.contexts.foundations.execution.workflow_runtime.contracts.runtime import (
    WORKFLOW_PROGRESSED_V1,
    StepExecutionDisposition,
)
from app.contexts.foundations.execution.workflow_runtime.infrastructure import (
    human_decisions,
    legacy_execution,
    remote_completion,
)
from app.contexts.foundations.execution.workflow_runtime.infrastructure.event_handler import (
    enqueue_ready_steps as enqueue_runtime_steps,
)
from app.contexts.foundations.execution.workflow_runtime.infrastructure.events import (
    workflow_progress_from_payload,
)
from app.contexts.foundations.integration.feishu_notify_person.entrypoints import (
    operations as feishu_notify_person_ops,
)
from app.contexts.foundations.integration.feishu_output.entrypoints import (
    operations as feishu_output_ops,
)
from app.contexts.foundations.knowledge.knowledge_indexing.infrastructure import (
    event_handler as knowledge_events,
)
from app.contexts.foundations.workforce.expert_management.infrastructure.sqlalchemy_query import (
    SQLAlchemyExpertSnapshotQuery,
)
from app.models.workflow import OutboxEvent
from app.platform.database import async_session_factory
from app.platform.eventing.inbox import EventEnvelope


class _EnvironmentSnapshotCache:
    def invalidate(self) -> None:
        environment_projection.invalidate_cache()


class _FeishuMechanicalPublisher:
    """组合根注入的机械发布器：桥接各对外 Context，供 workflow_runtime 无跨界依赖调用。

    按 draft 的 ``publish_key`` 派发：``feishu_publish`` → feishu_output 云文档/多维表格；
    ``feishu_notify_person_publish`` → 定向发送到指定的人/群（notify 自门控，关则安全跳过）；
    ``convene_consultation_publish`` → 真建会 + 定向通知四部门负责人（自开 session）；
    ``send_email_publish`` → 按 username 解析邮箱真发送（自开 session）。
    ponytail: 类名保留 Feishu 前缀但实为通用机械发布器（含建会/发信等非飞书目标）；私有类，
              重命名属纯 churn，故留名不改。扩展新机械发布时在此按 publish_key 再加一支。
    ponytail: at-least-once 外写，无幂等键——execute() 外写与 finalize() 提交非原子，其间 worker
              崩溃 / 租约被抢判 stale 时该步会被重新领取并再次 publish（真人验收「之后」重复建会 /
              发信 / 通知，无二次人工闸）。触发窗口窄、飞书集成默认关（canary=0 walking-skeleton），
              承接线上流量前收口：给 publish 传 `{run_id}:{step_id}:{publish_key}` 幂等键，convene
              建会 / send_email 落 dedupe，或建 step→external-effect 关联表。
    """

    async def available(self) -> bool:
        # 任一目标就绪即放行本步；具体 draft 的目标未配 → 对应 operations 内部 no-op 安全跳过。
        # ponytail: 本步整体以「任一对外目标就绪」为闸——各能力（convene 建会/send_email 发信）
        #           与飞书发布共用本闸，故所有目标全关时该步一并跳过（安全降级，生产必配至少一路）。
        #           要按 draft 精确门控时给 available() 传 capability_key 分档判定即可。
        from app.contexts.foundations.integration.send_email.entrypoints import (
            operations as send_email_ops,
        )

        return (
            await feishu_output_ops.feishu_output_available()
            or feishu_notify_person_ops.feishu_notify_person_available()
            or send_email_ops.send_email_available()
        )

    async def publish(self, draft: dict[str, object]) -> dict[str, object]:
        if draft.get("publish_key") == "feishu_notify_person_publish":
            sent = await feishu_notify_person_ops.send_to_recipient(
                str(draft.get("recipient", "")),
                bool(draft.get("is_chat", False)),
                str(draft.get("text", "")),
            )
            kind = "feishu_notify_person_sent" if sent else "feishu_notify_person_skipped"
            return {**draft, "kind": kind}
        if draft.get("publish_key") == "convene_consultation_publish":
            return await self._convene(draft)
        if draft.get("publish_key") == "send_email_publish":
            return await self._send_email(draft)
        return await feishu_output_ops.run_publish(dict(draft))

    async def _send_email(self, draft: dict[str, object]) -> dict[str, object]:
        # 机械发信步只拿到 compose 产出的 draft（无 session）→ 自开 session，按 username 解析邮箱。
        # 缺 username → 如实跳过。传输失败/未配 SMTP/无邮箱由 send_to_username 如实回 reason。
        # ponytail: dev 机械步无逐草稿重试——传输失败即落 email_skipped（reason 已记）。要「发失败自
        #           动重投」时改走 outbox 重派；当前 send_email 内已有网络类有界重试，够用。
        from app.contexts.foundations.integration.send_email.entrypoints import (
            operations as send_email_ops,
        )

        username = str(draft.get("username", ""))
        if not username:
            return {**draft, "kind": "email_skipped", "reason": "缺收件人账号，已安全跳过"}
        async with async_session_factory() as session:
            outcome = await send_email_ops.send_to_username(
                session,
                username=username,
                subject=str(draft.get("subject", "")),
                body=str(draft.get("body", "")),
            )
        if outcome.sent:
            return {**draft, "kind": "email_sent"}
        return {**draft, "kind": "email_skipped", "reason": outcome.reason or "未发送"}

    async def _convene(self, draft: dict[str, object]) -> dict[str, object]:
        # 机械会商步只拿到 compose 嵌入的 draft（无 session/user_id）→ 自开 session 真建会。
        # 缺 topic/creator_id（compose 未嵌发起人）→ 如实跳过，不臆造发起人。
        from app.contexts.foundations.integration.convene_consultation.entrypoints import (
            operations as convene_ops,
        )

        topic = str(draft.get("topic", ""))
        creator_raw = draft.get("creator_id")
        if not topic or not creator_raw:
            return {**draft, "kind": "convene_consultation_skipped"}
        async with async_session_factory() as session:
            outcome = await convene_ops.convene(
                session, topic=topic, creator_id=uuid.UUID(str(creator_raw))
            )
        return {
            "kind": "meeting",
            "meeting_id": str(outcome.meeting_id),
            "participant_user_ids": [str(uid) for uid in outcome.participant_user_ids],
            "participant_emails": list(outcome.participant_emails),
            "notified": list(outcome.notified),
            "skipped": list(outcome.skipped),
        }


_FEISHU_PUBLISHER = _FeishuMechanicalPublisher()


class _EnvironmentSnapshotRefresh:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def refresh(self) -> None:
        await environment_projection.refresh_env_doc(
            self._session,
            suppress_errors=False,
        )


_environment_snapshot_cache = _EnvironmentSnapshotCache()
ExternalEventHandler = Callable[[AsyncSession, OutboxEvent], Awaitable[None]]
ArchiveChannel = Callable[[AsyncSession, uuid.UUID], Awaitable[None]]
_external_event_handlers: dict[str, ExternalEventHandler] = {}


def register_event_handler(event_type: str, handler: ExternalEventHandler) -> None:
    """Register an outer handler for an event not owned by the runtime."""
    _external_event_handlers[event_type] = handler


def unregister_event_handler(event_type: str) -> None:
    """Remove a previously registered outer event handler."""
    _external_event_handlers.pop(event_type, None)


def _task_projection(session: AsyncSession) -> SQLAlchemyTaskManagementAdapter:
    return SQLAlchemyTaskManagementAdapter(session)


async def apply_step_completed(session: AsyncSession, envelope: EventEnvelope) -> bool:
    """入站投影：把 expert 回执写回停车 step（docs/23 §6.3）。

    装配期经 register_inbox_projector 注入。
    """
    return await remote_completion.apply_completed(
        session,
        envelope.payload or {},
        task_projection=_task_projection(session),
    )


async def enqueue_ready_steps(session: AsyncSession, workflow_id: uuid.UUID) -> int:
    return await enqueue_runtime_steps(
        session,
        workflow_id,
        task_projection=_task_projection(session),
    )


async def handle_event(
    session: AsyncSession,
    event: OutboxEvent,
    *,
    worker_id: str,
    agent_runner: AgentRunner,
    archive_channel: ArchiveChannel | None = None,
) -> StepExecutionDisposition:
    """Route one leased event to the Context operation that owns it."""
    if event.event_type == "workflow.advance":
        workflow_id = uuid.UUID(str(event.payload["workflow_run_id"]))
        await enqueue_ready_steps(session, workflow_id)
        return StepExecutionDisposition.complete()

    if event.event_type == "workflow.step.execute":
        return await legacy_execution.execute_step(
            session,
            event,
            worker_id=worker_id,
            agent_runner=agent_runner,
            task_projection=_task_projection(session),
            experts=SQLAlchemyExpertSnapshotQuery(session),
            publisher=_FEISHU_PUBLISHER,
        )

    if event.event_type == DISBAND_ARCHIVE_EVENT:
        raw_channel_id = event.payload.get("channel_id") or event.aggregate_id
        archive = archive_channel or archive_disbanded_channel
        await archive(session, uuid.UUID(str(raw_channel_id)))
        return StepExecutionDisposition.complete()

    if knowledge_events.handles(event.event_type):
        await knowledge_events.handle(event)
        return StepExecutionDisposition.complete()

    if event.event_type == ENVIRONMENT_SOURCE_CHANGED_V1:
        await handle_source_change(
            event,
            cache=_environment_snapshot_cache,
            refresh=_EnvironmentSnapshotRefresh(session),
        )
        return StepExecutionDisposition.complete()

    if event.event_type == WORKFLOW_PROGRESSED_V1:
        await _task_projection(session).apply(
            workflow_progress_from_payload(event.payload or {})
        )
        return StepExecutionDisposition.complete()

    if event.event_type == TASK_DECISION_RECORDED_V1:
        await human_decisions.apply_task_decision(
            session,
            task_decision_from_payload(event.payload or {}),
            task_projection=_task_projection(session),
        )
        return StepExecutionDisposition.complete()

    external_handler = _external_event_handlers.get(event.event_type)
    if external_handler is not None:
        await external_handler(session, event)
        return StepExecutionDisposition.complete()

    raise ValueError(f"未知 outbox event_type：{event.event_type}")


__all__ = [
    "ArchiveChannel",
    "ExternalEventHandler",
    "enqueue_ready_steps",
    "handle_event",
    "register_event_handler",
    "unregister_event_handler",
]
