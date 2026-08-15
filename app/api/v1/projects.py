"""个人工作台项目接口（docs/27 阶段 A1）：项目 CRUD + 归档。

红线/隔离：项目为个人数据，一律按当前登录人 owner 归属；非本人项目返回 404（不泄露存在性）。
归档是软生命周期标记（非删除），归档后不可编辑。
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.contexts.business.project_management.application.contracts import ProjectResult
from app.contexts.business.project_management.entrypoints import operations
from app.platform.database import get_db
from app.platform.http_runtime import ok

router = APIRouter(tags=["projects"])

DB = Annotated[AsyncSession, Depends(get_db)]


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    department_id: uuid.UUID | None = None


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None


def _data(item: ProjectResult) -> dict:
    return {
        "id": str(item.id),
        "name": item.name,
        "owner_id": str(item.owner_id),
        "description": item.description,
        "status": item.status,
        "department_id": str(item.department_id) if item.department_id else None,
        "archived_at": item.archived_at.isoformat() if item.archived_at else None,
        "create_time": item.create_time.isoformat(),
    }


@router.post("/projects")
async def create_project(body: ProjectCreate, db: DB, user: CurrentUser) -> dict:
    """新建项目（归属当前登录人）。"""
    item = await operations.create_project(
        db,
        owner_id=user.id,
        name=body.name,
        description=body.description,
        department_id=body.department_id,
    )
    return ok(_data(item))


@router.get("/projects")
async def list_projects(
    db: DB,
    user: CurrentUser,
    status: Annotated[str | None, Query(pattern="^(active|archived)$")] = None,
) -> dict:
    """我的项目列表（可按 active/archived 过滤）。"""
    items = await operations.list_projects(db, owner_id=user.id, status=status)
    return ok([_data(item) for item in items])


@router.get("/projects/{project_id}")
async def get_project(project_id: uuid.UUID, db: DB, user: CurrentUser) -> dict:
    """项目详情（仅本人）。"""
    return ok(_data(await operations.get_project(db, project_id, owner_id=user.id)))


@router.patch("/projects/{project_id}")
async def update_project(
    project_id: uuid.UUID, body: ProjectUpdate, db: DB, user: CurrentUser
) -> dict:
    """更新项目名称/描述（归档后不可编辑 → 400）。"""
    item = await operations.update_project(
        db, project_id, owner_id=user.id, name=body.name, description=body.description
    )
    return ok(_data(item))


@router.post("/projects/{project_id}/archive")
async def archive_project(project_id: uuid.UUID, db: DB, user: CurrentUser) -> dict:
    """归档项目（软标记，不可再编辑）。"""
    return ok(_data(await operations.archive_project(db, project_id, owner_id=user.id)))
