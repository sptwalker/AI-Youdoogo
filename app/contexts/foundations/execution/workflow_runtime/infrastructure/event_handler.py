"""Workflow-owned Outbox event preparation."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.execution.workflow_runtime.application.ports import (
    TaskProjectionPort,
)
from app.contexts.foundations.execution.workflow_runtime.infrastructure import (
    sqlalchemy_projection,
    sqlalchemy_repository,
    step_leases,
)
from app.models.workflow import RUN_CANCELLED, RUN_FAILED, RUN_SUCCEEDED, RUN_WAITING_HUMAN
from app.platform.outbox.repository import enqueue


async def enqueue_ready_steps(
    session: AsyncSession,
    workflow_id: uuid.UUID,
    *,
    task_projection: TaskProjectionPort,
) -> int:
    run = await sqlalchemy_repository.get_run(session, workflow_id)
    await sqlalchemy_projection.refresh_run_status(
        session, run, task_projection=task_projection
    )
    if run.status in (RUN_SUCCEEDED, RUN_FAILED, RUN_CANCELLED, RUN_WAITING_HUMAN):
        return 0
    steps = await sqlalchemy_repository.list_steps(session, workflow_id)
    ready = step_leases.ready_steps(steps)
    for step in ready:
        await enqueue(
            session,
            aggregate_type="workflow_step",
            aggregate_id=step.id,
            event_type="workflow.step.execute",
            dedupe_key=f"workflow-step:{step.id}:execute:v{step.version}",
            payload={
                "workflow_run_id": str(workflow_id),
                "workflow_step_id": str(step.id),
                "trace_id": str(run.trace_id),
            },
        )
    return len(ready)
