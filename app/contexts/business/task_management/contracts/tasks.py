"""Pure Task Management commands, results, and integration events."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class CreateTaskCommand:
    title: str
    task_type: str
    creator_id: uuid.UUID
    priority: str = "normal"
    assignee_expert_id: uuid.UUID | None = None
    parent_id: uuid.UUID | None = None
    sla_hours: int | None = None
    payload: tuple[tuple[str, object], ...] = ()
    step_number: int | None = None


@dataclass(frozen=True, slots=True)
class TransitionTaskCommand:
    task_id: uuid.UUID
    to_status: str
    principal_id: uuid.UUID | None
    note: str | None = None
    result_content: str | None = None


@dataclass(frozen=True, slots=True)
class TaskResult:
    task_id: uuid.UUID
    status: str
    title: str
    task_type: str
    version: int = 0


TASK_DECISION_RECORDED_V1 = "task.decision-recorded.v1"


@dataclass(frozen=True, slots=True)
class TaskDecisionRecordedV1:
    event_id: uuid.UUID
    task_id: uuid.UUID
    workflow_id: uuid.UUID
    workflow_step_id: uuid.UUID
    expected_step_version: int
    decision: str
    principal_id: uuid.UUID
    occurred_at: datetime
    contract_version: int = 1
