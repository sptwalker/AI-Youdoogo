"""One-way compatibility facade for Workflow Runtime projections."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.business.task_management.infrastructure.sqlalchemy_adapter import (
    SQLAlchemyTaskManagementAdapter,
)
from app.contexts.foundations.execution.workflow_runtime.infrastructure import (
    sqlalchemy_projection,
    sqlalchemy_repository,
)
from app.contexts.foundations.execution.workflow_runtime.infrastructure.events import (
    publish_workflow_progress,
)
from app.contexts.foundations.execution.workflow_runtime.infrastructure.sqlalchemy_state import (
    _run_progress_event,
    _step_progress_event,
)
from app.models.workflow import WorkflowRun, WorkflowStep
from app.platform.outbox.repository import utcnow


async def mirror_step_running(db: AsyncSession, step: WorkflowStep) -> None:
    run = await sqlalchemy_repository.get_run(db, step.workflow_run_id)
    await publish_workflow_progress(
        db,
        SQLAlchemyTaskManagementAdapter(db),
        _step_progress_event(run, step, "step.claimed", utcnow()),
    )


async def mirror_step_result(
    db: AsyncSession,
    step: WorkflowStep,
    *,
    result_content: str,
    succeeded: bool,
) -> None:
    del succeeded
    run = await sqlalchemy_repository.get_run(db, step.workflow_run_id)
    await publish_workflow_progress(
        db,
        SQLAlchemyTaskManagementAdapter(db),
        _step_progress_event(
            run,
            step,
            "step.waiting_human" if step.red_line else "step.completed",
            utcnow(),
            result_content=result_content,
            error=step.last_error,
        ),
    )


async def sync_parent_card(db: AsyncSession, run: WorkflowRun) -> None:
    await publish_workflow_progress(
        db,
        SQLAlchemyTaskManagementAdapter(db),
        _run_progress_event(run, f"workflow.{run.status}", utcnow()),
    )


async def refresh_run_status(db: AsyncSession, run: WorkflowRun) -> str:
    return await sqlalchemy_projection.refresh_run_status(
        db, run, task_projection=SQLAlchemyTaskManagementAdapter(db)
    )


progress = sqlalchemy_projection.progress


__all__ = [
    "mirror_step_result",
    "mirror_step_running",
    "progress",
    "refresh_run_status",
    "sync_parent_card",
]
