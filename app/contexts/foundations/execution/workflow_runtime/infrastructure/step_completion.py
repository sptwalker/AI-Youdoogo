"""Fenced workflow step completion and downstream output propagation."""

from __future__ import annotations

from typing import Any

from sqlalchemy import update
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
    _step_progress_event,
)
from app.models.workflow import (
    STEP_FAILED,
    STEP_RUNNING,
    STEP_SUCCEEDED,
    STEP_WAITING_HUMAN,
    WorkflowStep,
)
from app.platform.outbox.repository import utcnow


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
    await sqlalchemy_projection.refresh_run_status(session, run, task_projection=task_projection)
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
