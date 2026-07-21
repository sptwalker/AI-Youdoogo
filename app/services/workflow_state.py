"""Workflow state transitions, leases, human acceptance, and failure propagation."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.workflow import (
    RUN_FAILED,
    RUN_QUEUED,
    RUN_RUNNING,
    STEP_CANCELLED,
    STEP_FAILED,
    STEP_QUEUED,
    STEP_RUNNING,
    STEP_SUCCEEDED,
    STEP_WAITING_HUMAN,
    WorkflowRun,
    WorkflowStep,
)
from app.services import outbox_service, workflow_projection, workflow_repository

StepClaimStatus = Literal["claimed", "busy", "terminal"]


@dataclass(frozen=True, slots=True)
class StepClaimResult:
    status: StepClaimStatus
    step: WorkflowStep | None = None
    retry_at: datetime | None = None


def _before(value: datetime | None, now: datetime) -> bool:
    """SQLite 返回 naive datetime，统一转成与 now 相同的比较口径。"""
    if value is None:
        return False
    if value.tzinfo is None and now.tzinfo is not None:
        value = value.replace(tzinfo=now.tzinfo)
    return value < now


def ready_steps(steps: Sequence[WorkflowStep]) -> list[WorkflowStep]:
    """返回 queued 或租约过期 running 且依赖已成功的步骤。"""
    now = outbox_service.utcnow()
    succeeded = {str(step.id) for step in steps if step.status == STEP_SUCCEEDED}
    ready: list[WorkflowStep] = []
    for step in steps:
        expired = step.status == STEP_RUNNING and _before(step.lease_until, now)
        if step.status != STEP_QUEUED and not expired:
            continue
        if all(dep in succeeded for dep in (step.depends_on or [])):
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
    db: AsyncSession,
    step_id: uuid.UUID,
    *,
    worker_id: str,
    lease_seconds: int,
) -> StepClaimResult:
    """CAS 抢占并显式区分 claimed、active lease 和 terminal。"""
    step = await db.get(WorkflowStep, step_id)
    now = outbox_service.utcnow()
    if step is None or step.is_delete:
        return StepClaimResult("terminal", step)
    expired = step.status == STEP_RUNNING and _before(step.lease_until, now)
    if step.status != STEP_QUEUED and not expired:
        return _classify_unclaimed(step, now)
    expected = step.version
    prior_owner = step.lease_owner
    result = await db.execute(
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
        await db.refresh(step)
        return _classify_unclaimed(step, now)
    await db.flush()
    await db.refresh(step)
    run = await workflow_repository.get_run(db, step.workflow_run_id)
    if run.status == RUN_QUEUED:
        run.status = RUN_RUNNING
        run.started_at = now
        run.version += 1
    await workflow_projection.mirror_step_running(db, step)
    await workflow_repository.append_event(
        db,
        run,
        "step.reclaimed" if expired else "step.claimed",
        step=step,
        attempt=step.attempt,
        payload={"prior_lease_owner": prior_owner} if expired else {},
    )
    return StepClaimResult("claimed", step)


async def claim_step(
    db: AsyncSession,
    step_id: uuid.UUID,
    *,
    worker_id: str,
    lease_seconds: int,
) -> WorkflowStep | None:
    """兼容旧调用方：仅成功抢占时返回 WorkflowStep。"""
    result = await claim_step_result(
        db, step_id, worker_id=worker_id, lease_seconds=lease_seconds
    )
    return result.step if result.status == "claimed" else None


async def renew_step_lease(
    db: AsyncSession,
    step_id: uuid.UUID,
    *,
    worker_id: str,
    attempt: int,
    lease_seconds: int,
) -> bool:
    now = outbox_service.utcnow()
    result = await db.execute(
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
    await db.flush()
    return getattr(result, "rowcount", 0) == 1


async def complete_step(
    db: AsyncSession,
    step: WorkflowStep,
    *,
    worker_id: str,
    output_data: dict[str, Any],
    result_content: str,
    succeeded: bool,
    error: str | None = None,
) -> bool:
    now = outbox_service.utcnow()
    target = STEP_WAITING_HUMAN if step.red_line and succeeded else (
        STEP_SUCCEEDED if succeeded else STEP_FAILED
    )
    result = await db.execute(
        update(WorkflowStep)
        .where(
            WorkflowStep.id == step.id,
            WorkflowStep.status == STEP_RUNNING,
            WorkflowStep.lease_owner == worker_id,
            WorkflowStep.attempt == step.attempt,
        )
        .values(
            status=target,
            output_data=output_data,
            lease_owner=None,
            lease_until=None,
            completed_at=now,
            last_error=error[:2000] if error else None,
            version=WorkflowStep.version + 1,
        )
        .execution_options(synchronize_session=False)
    )
    if getattr(result, "rowcount", 0) != 1:
        return False
    await db.flush()
    step.status = target
    step.output_data = output_data
    step.last_error = error
    await workflow_projection.mirror_step_result(
        db, step, result_content=result_content, succeeded=succeeded
    )
    run = await workflow_repository.get_run(db, step.workflow_run_id)
    await workflow_repository.append_event(
        db,
        run,
        "step.waiting_human" if target == STEP_WAITING_HUMAN else "step.completed",
        step=step,
        attempt=step.attempt,
        payload={"succeeded": succeeded, "error": error},
    )
    await workflow_projection.refresh_run_status(db, run)
    return True


async def pipe_outputs(
    db: AsyncSession,
    step: WorkflowStep,
    *,
    datasets: list[dict[str, Any]],
    artifacts: list[dict[str, Any]],
) -> None:
    if not datasets and not artifacts:
        return
    steps = await workflow_repository.list_steps(db, step.workflow_run_id)
    sid = str(step.id)
    for downstream in steps:
        if sid not in (downstream.depends_on or []):
            continue
        data = dict(downstream.input_data or {})
        data["datasets"] = (data.get("datasets") or []) + datasets
        data["artifacts"] = (data.get("artifacts") or []) + artifacts
        downstream.input_data = data
    await db.flush()


async def accept_human_step(
    db: AsyncSession,
    task_card_id: uuid.UUID,
    *,
    operator_id: uuid.UUID | None,
) -> WorkflowRun | None:
    step = (
        await db.execute(
            select(WorkflowStep).where(
                WorkflowStep.task_card_id == task_card_id,
                WorkflowStep.status == STEP_WAITING_HUMAN,
            )
        )
    ).scalar_one_or_none()
    if step is None:
        return None
    step.status = STEP_SUCCEEDED
    step.version += 1
    step.completed_at = outbox_service.utcnow()
    run = await workflow_repository.get_run(db, step.workflow_run_id)
    await workflow_repository.append_event(
        db,
        run,
        "step.human_accepted",
        step=step,
        attempt=step.attempt,
        payload={"operator_id": str(operator_id) if operator_id else None},
    )
    await workflow_projection.refresh_run_status(db, run)
    await outbox_service.enqueue(
        db,
        aggregate_type="workflow",
        aggregate_id=run.id,
        event_type="workflow.advance",
        dedupe_key=f"workflow:{run.id}:resume:{step.id}:{step.version}",
        payload={"workflow_run_id": str(run.id), "trace_id": str(run.trace_id)},
    )
    return run


async def fail_from_outbox(
    db: AsyncSession,
    event: Any,
    *,
    error: str,
) -> WorkflowRun | None:
    raw_run_id = (event.payload or {}).get("workflow_run_id")
    if not raw_run_id:
        return None
    run = await workflow_repository.get_run(db, uuid.UUID(str(raw_run_id)))
    raw_step_id = (event.payload or {}).get("workflow_step_id")
    if raw_step_id:
        step = await db.get(WorkflowStep, uuid.UUID(str(raw_step_id)))
        terminal = (STEP_SUCCEEDED, STEP_WAITING_HUMAN, STEP_CANCELLED, STEP_FAILED)
        if step is not None and step.status not in terminal:
            step.status = STEP_FAILED
            step.last_error = error[:2000]
            step.lease_owner = None
            step.lease_until = None
            step.completed_at = outbox_service.utcnow()
            step.version += 1
            await workflow_repository.append_event(
                db,
                run,
                "step.retry_exhausted",
                step=step,
                attempt=step.attempt,
                payload={"outbox_event_id": str(event.id), "error": error[:2000]},
            )
            await workflow_projection.refresh_run_status(db, run)
            return run
    run.status = RUN_FAILED
    run.error_msg = error[:2000]
    run.completed_at = outbox_service.utcnow()
    run.version += 1
    await workflow_repository.append_event(
        db,
        run,
        "workflow.retry_exhausted",
        payload={"outbox_event_id": str(event.id), "error": error[:2000]},
    )
    if run.parent_task_id is not None:
        await workflow_projection.sync_parent_card(db, run)
    await db.flush()
    return run
