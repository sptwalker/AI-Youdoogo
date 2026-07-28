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


def _str_or_none(value: uuid.UUID | None) -> str | None:
    return str(value) if value is not None else None


def _run_progress_event(
    run: WorkflowRun, transition: str, occurred_at: datetime
) -> WorkflowProgressedV1:
    if run.parent_task_id is None:
        raise RuntimeError("workflow parent task projection is missing")
    # ponytail: 产品字段落 opaque payload（JSON 安全，uuid→str）；消费方 ACL 解码
    return WorkflowProgressedV1(
        event_id=uuid.uuid4(),
        workflow_id=run.id,
        run_version=run.version,
        occurred_at=occurred_at,
        transition=transition,
        run_status=WorkflowRunStatus(run.status),
        business_key=str(run.parent_task_id),
        payload={
            "parent_task_id": str(run.parent_task_id),
            "creator_id": str(run.creator_id),
            "title": run.title,
            "request_text": run.request_text,
            "expert_id": _str_or_none(run.assignee_agent_id),
        },
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
        run_status=WorkflowRunStatus(run.status),
        step_status=WorkflowStepStatus(step.status),
        step_id=step.id,
        step_version=step.version,
        step_number=step.step_no,
        business_key=str(step.task_card_id or run.parent_task_id),
        payload={
            "parent_task_id": str(run.parent_task_id),
            "creator_id": str(run.creator_id),
            "title": run.title,
            "request_text": run.request_text,
            "task_card_id": _str_or_none(step.task_card_id),
            "step_title": step.title,
            "capability_key": step.skill,
            "instruction": step.instruction,
            "red_line": step.red_line,
            "expert_id": _str_or_none(step.assignee_agent_id),
            "result_content": result_content,
        },
        error=error,
    )
