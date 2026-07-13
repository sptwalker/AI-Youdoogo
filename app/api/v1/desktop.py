"""真人工作桌面接口（F5a）：本人桌面 + admin 监督他人桌面。

每人只见自己（GET /desktop）；admin 可查他人做监督（GET /desktop/{user_id}）。
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, require_roles
from app.core.database import get_db
from app.core.exceptions import AppError, ok
from app.models.system import SysUser
from app.services import auth_service, desktop_service

router = APIRouter(prefix="/desktop", tags=["desktop"])

DB = Annotated[AsyncSession, Depends(get_db)]
Admin = Annotated[SysUser, Depends(require_roles("admin"))]


@router.get("")
async def get_my_desktop(db: DB, user: CurrentUser) -> dict:
    """我的工作桌面（待我处理统一队列 + 我的任务 + 对话/资料入口）。"""
    return ok(await desktop_service.get_desktop(db, user))


@router.get("/{user_id}")
async def get_user_desktop(user_id: uuid.UUID, db: DB, _: Admin) -> dict:
    """监督：查看某真人员工的桌面（仅 admin）。"""
    target = await auth_service.get_user_by_id(db, user_id)
    if target is None or target.is_delete:
        raise AppError("用户不存在", code=404, status_code=404)
    return ok(await desktop_service.get_desktop(db, target))
