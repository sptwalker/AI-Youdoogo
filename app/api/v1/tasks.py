"""任务卡接口：创建 / 列表 / 详情+日志 / 拆解 / 状态流转。

任意登录用户可创建与流转（首批为管理层小团队）；验收/驳回同样经人工操作，
落地 docs/04 红线：AI 仅建议/执行权，验收由真人确认。
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import scheduler
from app.api.deps import CurrentUser
from app.core.database import get_db
from app.core.exceptions import ok
from app.schemas.task import (
    DecomposeRequest,
    TaskCreate,
    TaskLogOut,
    TaskOut,
    TransitionRequest,
)
from app.services import task_service

router = APIRouter(prefix="/tasks", tags=["tasks"])

DB = Annotated[AsyncSession, Depends(get_db)]


@router.post("")
async def create_task(body: TaskCreate, db: DB, user: CurrentUser) -> dict:
    """创建任务卡。"""
    task = await task_service.create_task(
        db,
        title=body.title,
        task_type=body.task_type,
        creator_id=user.id,
        priority=body.priority,
        assignee_agent_id=body.assignee_agent_id,
        parent_id=body.parent_id,
        sla_hours=body.sla_hours,
        payload=body.payload,
    )
    return ok(TaskOut.model_validate(task).model_dump(mode="json"))


@router.get("")
async def list_tasks(
    db: DB,
    _: CurrentUser,
    status: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> dict:
    """任务列表（可按状态过滤，默认最多 100 条）。"""
    tasks = await task_service.list_tasks(db, status=status, limit=limit)
    return ok([TaskOut.model_validate(t).model_dump(mode="json") for t in tasks])


@router.get("/{task_id}")
async def get_task(task_id: uuid.UUID, db: DB, _: CurrentUser) -> dict:
    """任务详情 + 流转日志。"""
    task = await task_service.get_task(db, task_id)
    logs = await task_service.list_logs(db, task_id)
    return ok(
        {
            "task": TaskOut.model_validate(task).model_dump(mode="json"),
            "logs": [TaskLogOut.model_validate(x).model_dump(mode="json") for x in logs],
        }
    )


@router.post("/{task_id}/decompose")
async def decompose_task(
    task_id: uuid.UUID, body: DecomposeRequest, db: DB, user: CurrentUser
) -> dict:
    """把任务拆解为子任务。"""
    children = await task_service.decompose(
        db, task_id, [s.model_dump() for s in body.subtasks], creator_id=user.id
    )
    return ok([TaskOut.model_validate(c).model_dump(mode="json") for c in children])


@router.post("/{task_id}/transition")
async def transition_task(
    task_id: uuid.UUID, body: TransitionRequest, db: DB, user: CurrentUser
) -> dict:
    """状态流转（经状态机校验，非法流转返回错误）。"""
    task = await task_service.transition(
        db,
        task_id,
        body.to_status,
        operator_id=user.id,
        note=body.note,
        result_content=body.result_content,
    )
    return ok(TaskOut.model_validate(task).model_dump(mode="json"))


@router.post("/{task_id}/run")
async def run_task(task_id: uuid.UUID, db: DB, user: CurrentUser) -> dict:
    """调度中枢执行：驱动已分配智能体的任务卡自动跑到「已汇报」，待真人验收。"""
    task = await scheduler.run_task(db, task_id, operator_id=user.id)
    return ok(TaskOut.model_validate(task).model_dump(mode="json"))
