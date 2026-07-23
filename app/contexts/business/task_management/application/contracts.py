"""Plain commands and results for Task Management HTTP use cases."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class TaskPrincipal:
    id: uuid.UUID
    role_code: str
    department_id: uuid.UUID | None = None

    @property
    def sees_all_rows(self) -> bool:
        return self.role_code in {"admin", "executive"}


@dataclass(frozen=True, slots=True)
class CreateTaskRequest:
    title: str
    task_type: str
    creator_id: uuid.UUID
    priority: str = "normal"
    assignee_agent_id: uuid.UUID | None = None
    parent_id: uuid.UUID | None = None
    sla_hours: int | None = None
    payload: tuple[tuple[str, object], ...] = ()


@dataclass(frozen=True, slots=True)
class SubtaskRequest:
    title: str
    task_type: str | None = None
    priority: str | None = None
    assignee_agent_id: uuid.UUID | None = None
    payload: tuple[tuple[str, object], ...] = ()


@dataclass(frozen=True, slots=True)
class DecomposeTaskRequest:
    parent_id: uuid.UUID
    creator_id: uuid.UUID
    subtasks: tuple[SubtaskRequest, ...]


@dataclass(frozen=True, slots=True)
class TransitionTaskRequest:
    task_id: uuid.UUID
    to_status: str
    operator_id: uuid.UUID
    operator_role: str
    note: str | None = None
    result_content: str | None = None


@dataclass(frozen=True, slots=True)
class RunTaskRequest:
    task_id: uuid.UUID
    operator_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class TaskVisibility:
    unrestricted: bool
    principal_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class TaskView:
    id: uuid.UUID
    title: str
    task_type: str
    priority: str
    status: str
    creator_id: uuid.UUID
    assignee_agent_id: uuid.UUID | None
    parent_id: uuid.UUID | None
    sla_hours: int | None
    result_content: str | None
    create_time: datetime
    department_id: uuid.UUID | None = None
    assignee_user_id: uuid.UUID | None = None
    assignee_type: str = "agent"
    payload: tuple[tuple[str, object], ...] = ()
    step_no: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "title": self.title,
            "task_type": self.task_type,
            "priority": self.priority,
            "status": self.status,
            "creator_id": str(self.creator_id),
            "assignee_agent_id": (str(self.assignee_agent_id) if self.assignee_agent_id else None),
            "parent_id": str(self.parent_id) if self.parent_id else None,
            "sla_hours": self.sla_hours,
            "result_content": self.result_content,
            "create_time": self.create_time.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class TaskLogView:
    id: uuid.UUID
    from_status: str | None
    to_status: str
    operator_id: uuid.UUID | None
    note: str | None
    create_time: datetime

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "from_status": self.from_status,
            "to_status": self.to_status,
            "operator_id": str(self.operator_id) if self.operator_id else None,
            "note": self.note,
            "create_time": self.create_time.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class TaskDetailView:
    task: TaskView
    logs: tuple[TaskLogView, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "task": self.task.as_dict(),
            "logs": [log.as_dict() for log in self.logs],
        }


@dataclass(frozen=True, slots=True)
class TaskExecutionRequest:
    task_id: uuid.UUID
    title: str
    task_type: str
    payload: tuple[tuple[str, object], ...]
    assignee_agent_id: uuid.UUID
    operator_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class TaskExecutionResult:
    executor_id: uuid.UUID
    execution_status: str
    content: str
