"""Transport-neutral Task Management operations."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.business.task_management.application.contracts import (
    CreateTaskRequest,
    DecomposeTaskRequest,
    EditTaskRequest,
    RunTaskRequest,
    TaskPrincipal,
    TaskView,
    TransitionTaskRequest,
)
from app.contexts.business.task_management.infrastructure.composition import (
    build_task_management_application,
)
from app.contexts.business.task_management.infrastructure.sqlalchemy_adapter import (
    SQLAlchemyTaskManagementAdapter,
)
from app.contexts.foundations.execution.workflow_runtime import public as workflow_runtime


async def create_task(session: AsyncSession, request: CreateTaskRequest) -> dict[str, Any]:
    return (await build_task_management_application(session).create(request)).as_dict()


async def create_task_in_transaction(
    session: AsyncSession,
    request: CreateTaskRequest,
) -> TaskView:
    """Stage a Task in the caller-owned transaction for cross-Context workflows."""
    return await build_task_management_application(session).stage(request)


async def start_workflow(
    session: AsyncSession,
    command: workflow_runtime.StartWorkflowCommand,
) -> workflow_runtime.StartWorkflowResult:
    """Start Workflow Runtime with Task Management's owned projection adapter."""
    return await workflow_runtime.start_workflow(
        session,
        command,
        task_projection=SQLAlchemyTaskManagementAdapter(session),
    )


async def edit_task(session: AsyncSession, request: EditTaskRequest) -> dict[str, Any]:
    return (await build_task_management_application(session).edit(request)).as_dict()


async def list_tasks(
    session: AsyncSession,
    principal: TaskPrincipal,
    *,
    status: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    rows = await build_task_management_application(session).list(
        principal,
        status=status,
        limit=limit,
    )
    return [row.as_dict() for row in rows]


async def get_task(
    session: AsyncSession,
    principal: TaskPrincipal,
    task_id: uuid.UUID,
) -> dict[str, Any]:
    detail = await build_task_management_application(session).detail(principal, task_id)
    return detail.as_dict()


async def decompose_task(
    session: AsyncSession,
    request: DecomposeTaskRequest,
) -> list[dict[str, Any]]:
    rows = await build_task_management_application(session).decompose(request)
    return [row.as_dict() for row in rows]


async def transition_task(
    session: AsyncSession,
    request: TransitionTaskRequest,
) -> dict[str, Any]:
    result = await build_task_management_application(session).transition(request)
    return result.as_dict()


async def orchestration_progress(
    session: AsyncSession,
    task_id: uuid.UUID,
) -> dict[str, Any]:
    return await build_task_management_application(session).progress(task_id)


async def run_task(
    session: AsyncSession,
    request: RunTaskRequest,
) -> dict[str, Any]:
    result = await build_task_management_application(session).run(request)
    return result.as_dict()
