"""Propagate exhausted outbox retries into terminal workflow state."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.execution.workflow_runtime.application.ports import (
    TaskProjectionPort,
)
from app.contexts.foundations.execution.workflow_runtime.infrastructure import (
    sqlalchemy_projection,
    sqlalchemy_repository,
)
from app.contexts.foundations.execution.workflow_runtime.infrastructure.events import (
    publish_workflow_progress,
)
from app.contexts.foundations.execution.workflow_runtime.infrastructure.progress_events import (
    _run_progress_event,
)
from app.models.workflow import (
    RUN_FAILED,
    STEP_CANCELLED,
    STEP_FAILED,
    STEP_SUCCEEDED,
    STEP_WAITING_HUMAN,
    WorkflowRun,
    WorkflowStep,
)
from app.platform.outbox.repository import utcnow


async def fail_from_outbox(
    session: AsyncSession,
    event: Any,
    *,
    error: str,
    task_projection: TaskProjectionPort,
) -> WorkflowRun | None:
    raw_run_id = (event.payload or {}).get("workflow_run_id")
    if not raw_run_id:
        return None
    run = await sqlalchemy_repository.get_run(session, uuid.UUID(str(raw_run_id)))
    raw_step_id = (event.payload or {}).get("workflow_step_id")
    if raw_step_id:
        step = await session.get(WorkflowStep, uuid.UUID(str(raw_step_id)))
        terminal = (STEP_SUCCEEDED, STEP_WAITING_HUMAN, STEP_CANCELLED, STEP_FAILED)
        if step is not None and step.status not in terminal:
            step.status = STEP_FAILED
            step.last_error = error[:2000]
            step.lease_owner = None
            step.lease_until = None
            step.completed_at = utcnow()
            step.version += 1
            await sqlalchemy_repository.append_event(
                session,
                run,
                "step.retry_exhausted",
                step=step,
                attempt=step.attempt,
                payload={"outbox_event_id": str(event.id), "error": error[:2000]},
            )
            await sqlalchemy_projection.refresh_run_status(
                session, run, task_projection=task_projection
            )
            return run
    run.status = RUN_FAILED
    run.error_msg = error[:2000]
    run.completed_at = utcnow()
    run.version += 1
    await sqlalchemy_repository.append_event(
        session,
        run,
        "workflow.retry_exhausted",
        payload={"outbox_event_id": str(event.id), "error": error[:2000]},
    )
    if run.parent_task_id is not None:
        await publish_workflow_progress(
            session,
            task_projection,
            _run_progress_event(run, "workflow.failed", utcnow()),
        )
    await session.flush()
    return run
