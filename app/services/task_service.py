"""任务卡业务逻辑：创建 / 拆解 / 状态流转 / 查询，每次流转写日志。"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.models.task import TaskCard, TaskCardLog
from app.services import task_flow


async def _log(
    db: AsyncSession,
    task_id: uuid.UUID,
    from_status: str | None,
    to_status: str,
    operator_id: uuid.UUID | None,
    note: str | None = None,
) -> None:
    db.add(
        TaskCardLog(
            task_id=task_id, from_status=from_status, to_status=to_status,
            operator_id=operator_id, note=note,
        )
    )


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
) -> TaskCard:
    """创建任务卡（初始状态 created），写一条初始流转日志。"""
    task = TaskCard(
        title=title, task_type=task_type, creator_id=creator_id, priority=priority,
        assignee_agent_id=assignee_agent_id, parent_id=parent_id, sla_hours=sla_hours,
        payload=payload or {},
    )
    db.add(task)
    await db.flush()  # 取 task.id
    await _log(db, task.id, None, task_flow.CREATED, creator_id, "创建任务")
    await db.commit()
    await db.refresh(task)
    return task


async def get_task(db: AsyncSession, task_id: uuid.UUID) -> TaskCard:
    """取任务卡，不存在抛 404。"""
    task = await db.get(TaskCard, task_id)
    if task is None or task.is_delete:
        raise AppError("任务不存在", code=404, status_code=404)
    return task


async def decompose(
    db: AsyncSession,
    parent_id: uuid.UUID,
    subtasks: list[dict[str, Any]],
    *,
    creator_id: uuid.UUID,
) -> list[TaskCard]:
    """把一个任务拆解为若干子任务（子任务 parent_id 指向父任务）。

    Raises:
        AppError: 父任务不存在或子任务列表为空。
    """
    if not subtasks:
        raise AppError("子任务列表为空")
    parent = await get_task(db, parent_id)
    children: list[TaskCard] = []
    for sub in subtasks:
        title = sub.get("title")
        if not title:
            raise AppError("子任务缺少 title")
        child = TaskCard(
            title=title,
            task_type=sub.get("task_type", parent.task_type),
            creator_id=creator_id,
            priority=sub.get("priority", parent.priority),
            assignee_agent_id=sub.get("assignee_agent_id"),
            parent_id=parent.id,
            payload=sub.get("payload", {}),
        )
        db.add(child)
        await db.flush()
        await _log(db, child.id, None, task_flow.CREATED, creator_id, "拆解自父任务")
        children.append(child)
    await db.commit()
    for c in children:
        await db.refresh(c)
    return children


async def transition(
    db: AsyncSession,
    task_id: uuid.UUID,
    to_status: str,
    *,
    operator_id: uuid.UUID | None,
    note: str | None = None,
    result_content: str | None = None,
) -> TaskCard:
    """执行状态流转（经状态机校验），写流转日志。汇报时可附结果内容。

    Raises:
        AppError: 任务不存在或非法状态流转。
    """
    task = await get_task(db, task_id)
    task_flow.assert_transition(task.status, to_status)
    from_status = task.status
    task.status = to_status
    if result_content is not None:
        task.result_content = result_content
    await _log(db, task.id, from_status, to_status, operator_id, note)
    await db.commit()
    await db.refresh(task)
    return task


async def list_tasks(
    db: AsyncSession, *, status: str | None = None, parent_id: uuid.UUID | None = None
) -> list[TaskCard]:
    """列出任务卡（可按状态 / 父任务过滤），按创建时间倒序。"""
    stmt = select(TaskCard).where(TaskCard.is_delete.is_(False))
    if status:
        stmt = stmt.where(TaskCard.status == status)
    if parent_id:
        stmt = stmt.where(TaskCard.parent_id == parent_id)
    stmt = stmt.order_by(TaskCard.create_time.desc())
    return list((await db.execute(stmt)).scalars())


async def list_logs(db: AsyncSession, task_id: uuid.UUID) -> list[TaskCardLog]:
    """取任务的流转日志（按时间正序）。"""
    stmt = (
        select(TaskCardLog)
        .where(TaskCardLog.task_id == task_id)
        .order_by(TaskCardLog.create_time)
    )
    return list((await db.execute(stmt)).scalars())
