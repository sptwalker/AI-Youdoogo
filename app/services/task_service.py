"""One-way ORM-shaped facade for the Task Management bounded context."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.business.task_management.infrastructure.sqlalchemy_adapter import (
    SQLAlchemyTaskManagementAdapter,
)
from app.models.task import TaskCard, TaskCardLog

if TYPE_CHECKING:
    from app.models.system import SysUser


async def create_task(
    db: AsyncSession,
    *,
    title: str,
    task_type: str,
    creator_id: uuid.UUID,
    priority: str = "normal",
    assignee_agent_id: uuid.UUID | None = None,
    parent_id: uuid.UUID | None = None,
    sla_hours: int | None = None,
    payload: dict[str, Any] | None = None,
    step_no: int | None = None,
) -> TaskCard:
    return await SQLAlchemyTaskManagementAdapter(db).create_record(
        title=title,
        task_type=task_type,
        creator_id=creator_id,
        priority=priority,
        assignee_agent_id=assignee_agent_id,
        parent_id=parent_id,
        sla_hours=sla_hours,
        payload=payload,
        step_no=step_no,
    )


async def get_task(db: AsyncSession, task_id: uuid.UUID) -> TaskCard:
    return await SQLAlchemyTaskManagementAdapter(db).get_record(task_id)


async def decompose(
    db: AsyncSession,
    parent_id: uuid.UUID,
    subtasks: list[dict[str, Any]],
    *,
    creator_id: uuid.UUID,
) -> list[TaskCard]:
    return await SQLAlchemyTaskManagementAdapter(db).decompose_records(
        parent_id, subtasks, creator_id=creator_id
    )


async def transition(
    db: AsyncSession,
    task_id: uuid.UUID,
    to_status: str,
    *,
    operator_id: uuid.UUID | None,
    note: str | None = None,
    result_content: str | None = None,
) -> TaskCard:
    return await SQLAlchemyTaskManagementAdapter(db).transition_record(
        task_id,
        to_status,
        operator_id=operator_id,
        note=note,
        result_content=result_content,
    )


async def list_tasks(
    db: AsyncSession,
    *,
    status: str | None = None,
    parent_id: uuid.UUID | None = None,
    limit: int = 100,
    viewer: SysUser | None = None,
) -> list[TaskCard]:
    visibility_filter = None
    if viewer is not None:
        from app.services.permission_service import row_filter

        visibility_filter = row_filter
    return await SQLAlchemyTaskManagementAdapter(db).list_records(
        status=status,
        parent_id=parent_id,
        limit=limit,
        viewer=viewer,
        visibility_filter=visibility_filter,
    )


async def list_logs(db: AsyncSession, task_id: uuid.UUID) -> list[TaskCardLog]:
    return await SQLAlchemyTaskManagementAdapter(db).list_logs(task_id)
