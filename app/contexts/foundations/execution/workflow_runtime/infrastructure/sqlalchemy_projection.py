"""Workflow status aggregation and read projection."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.execution.workflow_runtime.application.ports import (
    TaskProjectionPort,
)
from app.contexts.foundations.execution.workflow_runtime.contracts.runtime import (
    WorkflowProgressedV1,
    WorkflowRunStatus,
)
from app.contexts.foundations.execution.workflow_runtime.infrastructure import (
    sqlalchemy_repository,
)
from app.contexts.foundations.execution.workflow_runtime.infrastructure.events import (
    publish_workflow_progress,
)
from app.contexts.shared_kernel import ResourceNotFound
from app.models.workflow import (
    RUN_CANCELLED,
    RUN_FAILED,
    RUN_QUEUED,
    RUN_RUNNING,
    RUN_SUCCEEDED,
    RUN_WAITING_HUMAN,
    STEP_CANCELLED,
    STEP_FAILED,
    STEP_RUNNING,
    STEP_SUCCEEDED,
    STEP_WAITING_HUMAN,
    WorkflowRun,
)
from app.platform.outbox.repository import utcnow


async def refresh_run_status(
    session: AsyncSession,
    run: WorkflowRun,
    *,
    task_projection: TaskProjectionPort,
) -> str:
    steps = await sqlalchemy_repository.list_steps(session, run.id)
    now = utcnow()
    if steps and all(step.status == STEP_SUCCEEDED for step in steps):
        status = RUN_SUCCEEDED
    elif any(step.status == STEP_CANCELLED for step in steps):
        status = RUN_CANCELLED
    elif any(step.status == STEP_FAILED for step in steps):
        status = RUN_FAILED
    elif any(step.status == STEP_WAITING_HUMAN for step in steps):
        status = RUN_WAITING_HUMAN
    elif any(step.status == STEP_RUNNING for step in steps):
        status = RUN_RUNNING
    elif any(step.status == STEP_SUCCEEDED for step in steps):
        status = RUN_RUNNING
    else:
        status = RUN_QUEUED
    changed = run.status != status
    run.status = status
    if status in (RUN_SUCCEEDED, RUN_FAILED, RUN_CANCELLED):
        run.completed_at = now
    if status == RUN_FAILED:
        run.error_msg = next(
            (step.last_error for step in steps if step.status == STEP_FAILED and step.last_error),
            "工作流步骤执行失败",
        )
    if changed:
        run.version += 1
        await sqlalchemy_repository.append_event(session, run, f"workflow.{status}")
        if run.parent_task_id is not None:
            await publish_workflow_progress(
                session,
                task_projection,
                WorkflowProgressedV1(
                    event_id=uuid.uuid4(),
                    workflow_id=run.id,
                    run_version=run.version,
                    occurred_at=now,
                    transition=f"workflow.{status}",
                    parent_task_id=run.parent_task_id,
                    creator_id=run.creator_id,
                    title=run.title,
                    request_text=run.request_text,
                    run_status=WorkflowRunStatus(status),
                    expert_id=run.assignee_agent_id,
                    error=run.error_msg,
                ),
            )
    await session.flush()
    return status


async def progress(session: AsyncSession, parent_task_id: uuid.UUID) -> dict[str, Any]:
    run = await sqlalchemy_repository.get_run_by_parent_task(session, parent_task_id)
    if run is None:
        raise ResourceNotFound("工作流不存在")
    steps = await sqlalchemy_repository.list_steps(session, run.id)
    completed = sum(1 for step in steps if step.status == STEP_SUCCEEDED)
    return {
        "workflow_id": str(run.id),
        "parent_id": str(parent_task_id),
        "parent_task_id": str(parent_task_id),
        "trace_id": str(run.trace_id),
        "status": run.status,
        "total": len(steps),
        "accepted": completed,
        "completed": completed,
        "done": run.status == RUN_SUCCEEDED,
        "awaiting_human": [
            str(step.task_card_id or step.id)
            for step in steps
            if step.status == STEP_WAITING_HUMAN
        ],
        "steps": [
            {
                "id": str(step.task_card_id or step.id),
                "task_card_id": str(step.task_card_id) if step.task_card_id else None,
                "workflow_step_id": str(step.id),
                "step_no": step.step_no,
                "title": step.title,
                "skill": step.skill,
                "status": step.status,
                "red_line": step.red_line,
                "attempt": step.attempt,
                "last_error": step.last_error,
                "output_data": step.output_data,
            }
            for step in steps
        ],
    }
