"""Recovery scan for expired Workflow Runtime leases."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.execution.workflow_runtime.infrastructure import (
    sqlalchemy_repository,
)
from app.models.workflow import OUTBOX_FAILED, STEP_RUNNING, OutboxEvent, WorkflowStep
from app.platform.outbox.repository import enqueue, utcnow

logger = logging.getLogger(__name__)


async def requeue_expired_steps(session: AsyncSession, *, batch_size: int = 100) -> int:
    now = utcnow()
    steps = list(
        (
            await session.execute(
                select(WorkflowStep)
                .where(
                    WorkflowStep.is_delete.is_(False),
                    WorkflowStep.status == STEP_RUNNING,
                    WorkflowStep.lease_until.is_not(None),
                    WorkflowStep.lease_until < now,
                )
                .order_by(WorkflowStep.lease_until)
                .limit(max(1, batch_size))
            )
        ).scalars()
    )
    created = 0
    for step in steps:
        dedupe_key = f"workflow-step:{step.id}:recover:v{step.version}"
        existing = (
            await session.execute(
                select(OutboxEvent).where(OutboxEvent.dedupe_key == dedupe_key)
            )
        ).scalar_one_or_none()
        if existing is not None and existing.status != OUTBOX_FAILED:
            continue
        run = await sqlalchemy_repository.get_run(session, step.workflow_run_id)
        if existing is not None:
            logger.error(
                "expired step recovery event already failed step=%s event=%s",
                step.id,
                existing.id,
            )
            continue
        await enqueue(
            session,
            aggregate_type="workflow_step",
            aggregate_id=step.id,
            event_type="workflow.step.execute",
            dedupe_key=dedupe_key,
            payload={
                "workflow_run_id": str(run.id),
                "workflow_step_id": str(step.id),
                "trace_id": str(run.trace_id),
                "recovery": True,
            },
        )
        await sqlalchemy_repository.append_event(
            session,
            run,
            "step.recovery_enqueued",
            step=step,
            attempt=step.attempt,
            payload={"expired_lease_owner": step.lease_owner, "step_version": step.version},
        )
        created += 1
    return created
