"""Transport-neutral Task Management operations."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.business.project_management import public as project_management
from app.contexts.business.task_management.application.contracts import (
    CreateTaskRequest,
    DecomposeTaskRequest,
    EditTaskRequest,
    RunTaskRequest,
    TaskPrincipal,
    TaskView,
    TransitionTaskRequest,
)
from app.contexts.business.task_management.domain import board
from app.contexts.business.task_management.infrastructure.composition import (
    build_task_management_application,
)
from app.contexts.business.task_management.infrastructure.sqlalchemy_adapter import (
    SQLAlchemyTaskManagementAdapter,
)
from app.contexts.foundations.execution.workflow_runtime import public as workflow_runtime


def _with_board(view: TaskView, now: datetime) -> dict[str, Any]:
    """把只读派生的看板泳道 + blocked 预警叠加到任务字典（不落库、不入状态机）。"""
    data = view.as_dict()
    data["lane"] = board.lane(view.status, view.archived_at)
    data["blocked"] = (
        board.is_blocked(view.status, view.update_time, now)
        if view.update_time is not None
        else False
    )
    return data


async def create_task(session: AsyncSession, request: CreateTaskRequest) -> dict[str, Any]:
    if request.project_id is not None:
        # 信任边界 + 行级隔离：项目须存在且归创建人；否则 get_project 抛 404。
        await project_management.get_project(
            session, request.project_id, owner_id=request.creator_id
        )
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
    project_id: uuid.UUID | None = None,
    include_archived: bool = False,
) -> list[dict[str, Any]]:
    rows = await build_task_management_application(session).list(
        principal,
        status=status,
        limit=limit,
        project_id=project_id,
        include_archived=include_archived,
    )
    # ponytail: 用 wall-clock now 算 live「静止」预警；纯函数在单测里注入 now 保证确定性
    now = datetime.now(UTC)
    return [_with_board(row, now) for row in rows]


async def archive_task(
    session: AsyncSession,
    principal: TaskPrincipal,
    task_id: uuid.UUID,
) -> dict[str, Any]:
    result = await build_task_management_application(session).archive(principal, task_id)
    return result.as_dict()


async def get_task(
    session: AsyncSession,
    principal: TaskPrincipal,
    task_id: uuid.UUID,
) -> dict[str, Any]:
    detail = await build_task_management_application(session).detail(principal, task_id)
    data = detail.as_dict()
    data["task"] = _with_board(detail.task, datetime.now(UTC))
    return data


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
