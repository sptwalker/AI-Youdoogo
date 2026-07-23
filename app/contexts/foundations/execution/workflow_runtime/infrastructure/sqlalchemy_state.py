"""Workflow leases, fenced transitions, human decisions, and failure propagation."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.business.task_management.contracts.tasks import TaskDecisionRecordedV1
from app.contexts.foundations.execution.workflow_runtime.application.ports import (
    TaskProjectionPort,
)
from app.contexts.foundations.execution.workflow_runtime.contracts.runtime import (
    WorkflowProgressedV1,
    WorkflowRunStatus,
    WorkflowStepStatus,
)
from app.contexts.foundations.execution.workflow_runtime.infrastructure import (
    sqlalchemy_projection,
    sqlalchemy_repository,
)
from app.contexts.foundations.execution.workflow_runtime.infrastructure.events import (
    publish_workflow_progress,
)
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
from app.platform.outbox.repository import enqueue, utcnow

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


async def complete_step(
    session: AsyncSession,
    step: WorkflowStep,
    *,
    worker_id: str,
    output_data: dict[str, Any],
    result_content: str,
    succeeded: bool,
    error: str | None,
    task_projection: TaskProjectionPort,
    expected_version: int | None = None,
) -> bool:
    now = utcnow()
    target = (
        STEP_WAITING_HUMAN
        if step.red_line and succeeded
        else (STEP_SUCCEEDED if succeeded else STEP_FAILED)
    )
    expected_version = step.version if expected_version is None else expected_version
    result = await session.execute(
        update(WorkflowStep)
        .where(
            WorkflowStep.id == step.id,
            WorkflowStep.status == STEP_RUNNING,
            WorkflowStep.lease_owner == worker_id,
            WorkflowStep.attempt == step.attempt,
            WorkflowStep.version == expected_version,
        )
        .values(
            status=target,
            output_data=output_data,
            lease_owner=None,
            lease_until=None,
            completed_at=now,
            last_error=error[:2000] if error else None,
            version=expected_version + 1,
        )
        .execution_options(synchronize_session=False)
    )
    if getattr(result, "rowcount", 0) != 1:
        return False
    await session.flush()
    step.status = target
    step.output_data = output_data
    step.last_error = error
    step.lease_owner = None
    step.lease_until = None
    step.completed_at = now
    step.version = expected_version + 1
    run = await sqlalchemy_repository.get_run(session, step.workflow_run_id)
    await sqlalchemy_repository.append_event(
        session,
        run,
        "step.waiting_human" if target == STEP_WAITING_HUMAN else "step.completed",
        step=step,
        attempt=step.attempt,
        payload={"succeeded": succeeded, "error": error},
    )
    await sqlalchemy_projection.refresh_run_status(
        session, run, task_projection=task_projection
    )
    await publish_workflow_progress(
        session,
        task_projection,
        _step_progress_event(
            run,
            step,
            "step.waiting_human" if target == STEP_WAITING_HUMAN else "step.completed",
            now,
            result_content=result_content,
            error=error,
        ),
    )
    return True


async def pipe_outputs(
    session: AsyncSession,
    step: WorkflowStep,
    *,
    datasets: list[dict[str, Any]],
    artifacts: list[dict[str, Any]],
) -> None:
    if not datasets and not artifacts:
        return
    steps = await sqlalchemy_repository.list_steps(session, step.workflow_run_id)
    step_id = str(step.id)
    for downstream in steps:
        if step_id not in (downstream.depends_on or []):
            continue
        data = dict(downstream.input_data or {})
        data["datasets"] = (data.get("datasets") or []) + datasets
        data["artifacts"] = (data.get("artifacts") or []) + artifacts
        downstream.input_data = data
    await session.flush()


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
    await sqlalchemy_projection.refresh_run_status(
        session, run, task_projection=task_projection
    )
    if event.decision == "accepted":
        await enqueue(
            session,
            aggregate_type="workflow",
            aggregate_id=run.id,
            event_type="workflow.advance",
            dedupe_key=(
                f"workflow:{run.id}:resume:{step.id}:v{event.expected_step_version}"
            ),
            payload={"workflow_run_id": str(run.id), "trace_id": str(run.trace_id)},
        )
    return run


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


def _run_progress_event(
    run: WorkflowRun, transition: str, occurred_at: datetime
) -> WorkflowProgressedV1:
    if run.parent_task_id is None:
        raise RuntimeError("workflow parent task projection is missing")
    return WorkflowProgressedV1(
        event_id=uuid.uuid4(),
        workflow_id=run.id,
        run_version=run.version,
        occurred_at=occurred_at,
        transition=transition,
        parent_task_id=run.parent_task_id,
        creator_id=run.creator_id,
        title=run.title,
        request_text=run.request_text,
        run_status=WorkflowRunStatus(run.status),
        expert_id=run.assignee_agent_id,
        error=run.error_msg,
    )


def _step_progress_event(
    run: WorkflowRun,
    step: WorkflowStep,
    transition: str,
    occurred_at: datetime,
    *,
    result_content: str | None = None,
    error: str | None = None,
) -> WorkflowProgressedV1:
    if run.parent_task_id is None:
        raise RuntimeError("workflow parent task projection is missing")
    return WorkflowProgressedV1(
        event_id=uuid.uuid4(),
        workflow_id=run.id,
        run_version=run.version,
        occurred_at=occurred_at,
        transition=transition,
        parent_task_id=run.parent_task_id,
        creator_id=run.creator_id,
        title=run.title,
        request_text=run.request_text,
        run_status=WorkflowRunStatus(run.status),
        step_status=WorkflowStepStatus(step.status),
        step_id=step.id,
        task_card_id=step.task_card_id,
        step_version=step.version,
        step_number=step.step_no,
        step_title=step.title,
        capability_key=step.skill,
        instruction=step.instruction,
        red_line=step.red_line,
        expert_id=step.assignee_agent_id,
        result_content=result_content,
        error=error,
    )
