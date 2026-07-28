"""任务卡接口：创建 / 列表 / 详情+日志 / 拆解 / 状态流转。

任意登录用户可创建与流转（首批为管理层小团队）；验收/驳回同样经人工操作，
落地 docs/04 红线：AI 仅建议/执行权，验收由真人确认。
"""

import uuid
from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, HumanUser
from app.contexts.business.task_management import public as task_management
from app.platform.database import get_db
from app.platform.http_runtime import ok
from app.schemas.task import (
    DecomposeRequest,
    TaskCreate,
    TaskEdit,
    TransitionRequest,
)

router = APIRouter(prefix="/tasks", tags=["tasks"])

DB = Annotated[AsyncSession, Depends(get_db)]


class _UserLike(Protocol):
    @property
    def id(self) -> uuid.UUID: ...

    @property
    def role_code(self) -> str: ...

    @property
    def department_id(self) -> uuid.UUID | None: ...


def _principal(user: _UserLike) -> task_management.TaskPrincipal:
    return task_management.TaskPrincipal(
        id=user.id,
        role_code=user.role_code,
        department_id=user.department_id,
    )


@router.post("")
async def create_task(body: TaskCreate, db: DB, user: CurrentUser) -> dict:
    """创建任务卡。"""
    return ok(
        await task_management.create_task(
            db,
            task_management.CreateTaskRequest(
                title=body.title,
                task_type=body.task_type,
                creator_id=user.id,
                priority=body.priority,
                assignee_agent_id=body.assignee_agent_id,
                parent_id=body.parent_id,
                sla_hours=body.sla_hours,
                payload=tuple(body.payload.items()),
            ),
        )
    )


@router.patch("/{task_id}")
async def edit_task(
    task_id: uuid.UUID, body: TaskEdit, db: DB, _: CurrentUser
) -> dict:
    """编辑/补指派任务（仅 created/rejected 未开跑可改，非法状态返回错误，P2-12）。"""
    return ok(
        await task_management.edit_task(
            db,
            task_management.EditTaskRequest(
                task_id=task_id,
                title=body.title,
                priority=body.priority,
                assignee_agent_id=body.assignee_agent_id,
            ),
        )
    )


@router.get("")
async def list_tasks(
    db: DB,
    user: CurrentUser,
    status: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> dict:
    """任务列表（行级可见性：普通员工只见本人/本部门/派给己，管理层全见）。"""
    return ok(
        await task_management.list_tasks(
            db,
            _principal(user),
            status=status,
            limit=limit,
        )
    )


@router.get("/{task_id}")
async def get_task(task_id: uuid.UUID, db: DB, user: CurrentUser) -> dict:
    """任务详情 + 流转日志（行级可见性守卫）。"""
    return ok(await task_management.get_task(db, _principal(user), task_id))


@router.post("/{task_id}/decompose")
async def decompose_task(
    task_id: uuid.UUID, body: DecomposeRequest, db: DB, user: CurrentUser
) -> dict:
    """把任务拆解为子任务。"""
    return ok(
        await task_management.decompose_task(
            db,
            task_management.DecomposeTaskRequest(
                parent_id=task_id,
                creator_id=user.id,
                subtasks=tuple(
                    task_management.SubtaskRequest(
                        title=subtask.title,
                        task_type=subtask.task_type,
                        priority=subtask.priority,
                        assignee_agent_id=subtask.assignee_agent_id,
                        payload=tuple(subtask.payload.items()),
                    )
                    for subtask in body.subtasks
                ),
            ),
        )
    )


@router.post("/{task_id}/transition")
async def transition_task(
    task_id: uuid.UUID, body: TransitionRequest, db: DB, user: HumanUser
) -> dict:
    """状态流转（经状态机校验，非法流转返回错误）。验收=生效动作，require_human 守卫。"""
    return ok(
        await task_management.transition_task(
            db,
            task_management.TransitionTaskRequest(
                task_id=task_id,
                to_status=body.to_status,
                operator_id=user.id,
                operator_role=user.role_code,
                note=body.note,
                result_content=body.result_content,
            ),
        )
    )


@router.get("/{task_id}/orchestration")
async def orchestration_progress(task_id: uuid.UUID, db: DB, _: CurrentUser) -> dict:
    """编排进度快照（父编排卡 id → 各步骤状态/红线/等真人）。供前端进度卡渲染/刷新。"""
    return ok(
        await task_management.orchestration_progress(
            db,
            task_id,
        )
    )


@router.post("/{task_id}/run")
async def run_task(task_id: uuid.UUID, db: DB, user: CurrentUser) -> dict:
    """调度中枢执行：驱动已分配智能体的任务卡自动跑到「已汇报」，待真人验收。"""
    return ok(
        await task_management.run_task(
            db,
            task_management.RunTaskRequest(task_id=task_id, operator_id=user.id),
        )
    )
