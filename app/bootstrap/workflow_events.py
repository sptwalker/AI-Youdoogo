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
    legacy_execution,
)
from app.contexts.foundations.execution.workflow_runtime.infrastructure.event_handler import (
    enqueue_ready_steps as enqueue_runtime_steps,
)
from app.contexts.foundations.execution.workflow_runtime.infrastructure.events import (
    workflow_progress_from_payload,
)
from app.contexts.foundations.execution.workflow_runtime.infrastructure.sqlalchemy_state import (
    apply_task_decision,
)
from app.contexts.foundations.knowledge.knowledge_indexing.infrastructure import (
    event_handler as knowledge_events,
)
from app.contexts.foundations.workforce.expert_management.infrastructure.sqlalchemy_query import (
    SQLAlchemyExpertSnapshotQuery,
)
from app.models.workflow import OutboxEvent


class _EnvironmentSnapshotCache:
    def invalidate(self) -> None:
        environment_projection.invalidate_cache()


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
        await apply_task_decision(
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
