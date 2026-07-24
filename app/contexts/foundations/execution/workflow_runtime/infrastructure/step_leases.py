"""Workflow step readiness, fenced claims, and lease renewal."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from sqlalchemy import or_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.execution.workflow_runtime.application.ports import (
    TaskProjectionPort,
)
from app.contexts.foundations.execution.workflow_runtime.infrastructure import (
    sqlalchemy_repository,
)
from app.contexts.foundations.execution.workflow_runtime.infrastructure.events import (
    publish_workflow_progress,
)
from app.contexts.foundations.execution.workflow_runtime.infrastructure.progress_events import (
    _run_progress_event,
    _step_progress_event,
)
from app.models.workflow import (
    RUN_QUEUED,
    RUN_RUNNING,
    STEP_CANCELLED,
    STEP_FAILED,
    STEP_QUEUED,
    STEP_RUNNING,
    STEP_SUCCEEDED,
    STEP_WAITING_HUMAN,
    WorkflowStep,
)
from app.platform.outbox.repository import utcnow

StepClaimStatus = Literal["claimed", "busy", "terminal"]


@dataclass(frozen=True, slots=True)
class StepClaimResult:
    status: StepClaimStatus
    step: WorkflowStep | None = None
    retry_at: datetime | None = None


def _before(value: datetime | None, now: datetime) -> bool:
    if value is None:
        return False
    if value.tzinfo is None and now.tzinfo is not None:
        value = value.replace(tzinfo=now.tzinfo)
    return value < now


def ready_steps(steps: Sequence[WorkflowStep]) -> list[WorkflowStep]:
    now = utcnow()
    succeeded = {str(step.id) for step in steps if step.status == STEP_SUCCEEDED}
    ready: list[WorkflowStep] = []
    for step in steps:
        expired = step.status == STEP_RUNNING and _before(step.lease_until, now)
        if step.status != STEP_QUEUED and not expired:
            continue
        if all(dependency in succeeded for dependency in (step.depends_on or [])):
            ready.append(step)
    return ready


def _classify_unclaimed(step: WorkflowStep | None, now: datetime) -> StepClaimResult:
    if step is None or step.is_delete:
        return StepClaimResult("terminal", step)
    if step.status == STEP_RUNNING and not _before(step.lease_until, now):
        return StepClaimResult("busy", step, step.lease_until)
    if step.status in (STEP_SUCCEEDED, STEP_WAITING_HUMAN, STEP_FAILED, STEP_CANCELLED):
        return StepClaimResult("terminal", step)
    return StepClaimResult("busy", step, now + timedelta(seconds=1))


async def claim_step_result(
    session: AsyncSession,
    step_id: uuid.UUID,
    *,
    worker_id: str,
    lease_seconds: int,
    task_projection: TaskProjectionPort,
) -> StepClaimResult:
    step = await session.get(WorkflowStep, step_id)
    now = utcnow()
    if step is None or step.is_delete:
        return StepClaimResult("terminal", step)
    expired = step.status == STEP_RUNNING and _before(step.lease_until, now)
    if step.status != STEP_QUEUED and not expired:
        return _classify_unclaimed(step, now)
    expected = step.version
    prior_owner = step.lease_owner
    result = await session.execute(
        update(WorkflowStep)
        .where(
            WorkflowStep.id == step.id,
            WorkflowStep.version == expected,
            or_(
                WorkflowStep.status == STEP_QUEUED,
                (WorkflowStep.status == STEP_RUNNING) & (WorkflowStep.lease_until < now),
            ),
        )
        .values(
            status=STEP_RUNNING,
            version=expected + 1,
            attempt=WorkflowStep.attempt + 1,
            lease_owner=worker_id,
            lease_until=now + timedelta(seconds=lease_seconds),
            started_at=now,
            completed_at=None,
            last_error=None,
        )
        .execution_options(synchronize_session=False)
    )
    if getattr(result, "rowcount", 0) != 1:
        await session.refresh(step)
        return _classify_unclaimed(step, now)
    await session.flush()
    await session.refresh(step)
    run = await sqlalchemy_repository.get_run(session, step.workflow_run_id)
    run_changed = run.status == RUN_QUEUED
    if run_changed:
        run.status = RUN_RUNNING
        run.started_at = now
        run.version += 1
    await publish_workflow_progress(
        session,
        task_projection,
        _step_progress_event(
            run,
            step,
            "step.reclaimed" if expired else "step.claimed",
            now,
        ),
    )
    if run_changed and run.parent_task_id is not None:
        await publish_workflow_progress(
            session,
            task_projection,
            _run_progress_event(run, "workflow.running", now),
        )
    await sqlalchemy_repository.append_event(
        session,
        run,
        "step.reclaimed" if expired else "step.claimed",
        step=step,
        attempt=step.attempt,
        payload={"prior_lease_owner": prior_owner} if expired else {},
    )
    return StepClaimResult("claimed", step)


async def claim_step(
    session: AsyncSession,
    step_id: uuid.UUID,
    *,
    worker_id: str,
    lease_seconds: int,
    task_projection: TaskProjectionPort,
) -> WorkflowStep | None:
    result = await claim_step_result(
        session,
        step_id,
        worker_id=worker_id,
        lease_seconds=lease_seconds,
        task_projection=task_projection,
    )
    return result.step if result.status == "claimed" else None


async def renew_step_lease(
    session: AsyncSession,
    step_id: uuid.UUID,
    *,
    worker_id: str,
    attempt: int,
    lease_seconds: int,
) -> bool:
    now = utcnow()
    result = await session.execute(
        update(WorkflowStep)
        .where(
            WorkflowStep.id == step_id,
            WorkflowStep.status == STEP_RUNNING,
            WorkflowStep.lease_owner == worker_id,
            WorkflowStep.attempt == attempt,
            WorkflowStep.lease_until >= now,
        )
        .values(lease_until=now + timedelta(seconds=lease_seconds))
        .execution_options(synchronize_session=False)
    )
    await session.flush()
    return getattr(result, "rowcount", 0) == 1
