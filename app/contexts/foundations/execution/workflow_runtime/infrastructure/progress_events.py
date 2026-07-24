"""Map durable workflow state to task projection progress events."""

from __future__ import annotations

import uuid
from datetime import datetime

from app.contexts.foundations.execution.workflow_runtime.contracts.runtime import (
    WorkflowProgressedV1,
    WorkflowRunStatus,
    WorkflowStepStatus,
)
from app.models.workflow import WorkflowRun, WorkflowStep


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
