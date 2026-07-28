"""Task Management-owned persistence and transaction ports."""

from __future__ import annotations

import uuid
from typing import Any, Protocol

from app.contexts.business.task_management.application.contracts import (
    CreateTaskRequest,
    EditTaskRequest,
    TaskExecutionRequest,
    TaskExecutionResult,
    TaskLogView,
    TaskView,
    TaskVisibility,
)


class TaskCardRepositoryPort(Protocol):
    async def create_view(self, request: CreateTaskRequest) -> TaskView: ...

    async def get_view(self, task_id: uuid.UUID) -> TaskView: ...

    async def edit_view(self, request: EditTaskRequest) -> TaskView: ...

    async def list_views(
        self,
        *,
        status: str | None,
        parent_id: uuid.UUID | None,
        limit: int,
        visibility: TaskVisibility,
    ) -> tuple[TaskView, ...]: ...

    async def list_log_views(self, task_id: uuid.UUID) -> tuple[TaskLogView, ...]: ...

    async def transition_view(
        self,
        task_id: uuid.UUID,
        to_status: str,
        *,
        operator_id: uuid.UUID | None,
        note: str | None = None,
        result_content: str | None = None,
    ) -> TaskView: ...


class TaskTransactionPort(Protocol):
    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


class TaskWorkflowPort(Protocol):
    async def resume_if_step(
        self, task: TaskView, *, operator_id: uuid.UUID
    ) -> dict[str, Any] | None: ...

    async def progress(self, parent_task_id: uuid.UUID) -> dict[str, Any]: ...


class TaskExecutionPort(Protocol):
    async def execute(self, request: TaskExecutionRequest) -> TaskExecutionResult: ...


class TaskAuditPort(Protocol):
    async def record_decision(
        self,
        *,
        task: TaskView,
        actor_id: uuid.UUID,
        actor_role: str,
        decision: str,
    ) -> None: ...
