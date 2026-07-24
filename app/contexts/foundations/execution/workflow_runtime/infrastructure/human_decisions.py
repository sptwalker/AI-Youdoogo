"""Apply idempotent human decisions to waiting workflow steps."""

from __future__ import annotations

import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.business.task_management.contracts.tasks import TaskDecisionRecordedV1
from app.contexts.foundations.execution.workflow_runtime.application.ports import (
    TaskProjectionPort,
)
from app.contexts.foundations.execution.workflow_runtime.infrastructure import (
    sqlalchemy_projection,
    sqlalchemy_repository,
)
from app.models.workflow import (
    STEP_FAILED,
    STEP_SUCCEEDED,
    STEP_WAITING_HUMAN,
    WorkflowRun,
    WorkflowStep,
)
from app.platform.outbox.repository import enqueue, utcnow


async def accept_human_step(
    session: AsyncSession,
    task_card_id: uuid.UUID,
    *,
    operator_id: uuid.UUID | None,
    task_projection: TaskProjectionPort,
) -> WorkflowRun | None:
    if operator_id is None:
        return None
    step = (
        await session.execute(
            select(WorkflowStep).where(
                WorkflowStep.task_card_id == task_card_id,
                WorkflowStep.status == STEP_WAITING_HUMAN,
            )
        )
    ).scalar_one_or_none()
    if step is None:
        return None
    return await apply_task_decision(
        session,
        TaskDecisionRecordedV1(
            event_id=uuid.uuid4(),
            task_id=task_card_id,
            workflow_id=step.workflow_run_id,
            workflow_step_id=step.id,
            expected_step_version=step.version,
            decision="accepted",
            principal_id=operator_id,
            occurred_at=utcnow(),
        ),
        task_projection=task_projection,
    )


async def apply_task_decision(
    session: AsyncSession,
    event: TaskDecisionRecordedV1,
    *,
    task_projection: TaskProjectionPort,
) -> WorkflowRun | None:
    if event.decision not in {"accepted", "rejected"}:
        return None
    target = STEP_SUCCEEDED if event.decision == "accepted" else STEP_FAILED
    now = utcnow()
    result = await session.execute(
        update(WorkflowStep)
        .where(
            WorkflowStep.id == event.workflow_step_id,
            WorkflowStep.workflow_run_id == event.workflow_id,
            WorkflowStep.task_card_id == event.task_id,
            WorkflowStep.status == STEP_WAITING_HUMAN,
            WorkflowStep.version == event.expected_step_version,
        )
        .values(
            status=target,
            version=event.expected_step_version + 1,
            completed_at=now,
            last_error=("真人驳回" if event.decision == "rejected" else None),
        )
        .execution_options(synchronize_session=False)
    )
    if getattr(result, "rowcount", 0) != 1:
        return None
    step = await session.get(WorkflowStep, event.workflow_step_id)
    if step is None:
        return None
    await session.refresh(step)
    run = await sqlalchemy_repository.get_run(session, event.workflow_id)
    await sqlalchemy_repository.append_event(
        session,
        run,
        f"step.human_{event.decision}",
        step=step,
        attempt=step.attempt,
        payload={
            "operator_id": str(event.principal_id),
            "task_decision_event_id": str(event.event_id),
        },
    )
    await sqlalchemy_projection.refresh_run_status(session, run, task_projection=task_projection)
    if event.decision == "accepted":
        await enqueue(
            session,
            aggregate_type="workflow",
            aggregate_id=run.id,
            event_type="workflow.advance",
            dedupe_key=(f"workflow:{run.id}:resume:{step.id}:v{event.expected_step_version}"),
            payload={"workflow_run_id": str(run.id), "trace_id": str(run.trace_id)},
        )
    return run
