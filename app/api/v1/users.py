"""用户管理接口（仅 admin）。"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_roles
from app.core.database import get_db
from app.core.exceptions import AppError, ok
from app.models.system import SysUser
from app.schemas.auth import UserCreate, UserOut, UserUpdate
from app.services import auth_service

router = APIRouter(prefix="/users", tags=["users"])

DB = Annotated[AsyncSession, Depends(get_db)]
AdminUser = Annotated[SysUser, Depends(require_roles("admin"))]


@router.post("")
async def create_user(body: UserCreate, db: DB, _: AdminUser) -> dict:
    """创建用户。"""
    user = await auth_service.create_user(db, body)
    return ok(UserOut.model_validate(user).model_dump(mode="json"))


@router.get("")
async def list_users(db: DB, _: AdminUser) -> dict:
    """用户列表。"""
    users = await auth_service.list_users(db)
    return ok([UserOut.model_validate(u).model_dump(mode="json") for u in users])


@router.patch("/{user_id}")
async def update_user(user_id: uuid.UUID, body: UserUpdate, db: DB, admin: AdminUser) -> dict:
    """更新用户（改密/停用/角色/部门）。禁止停用或降权自己，防 admin 自锁。"""
    if user_id == admin.id and (
        body.is_active is False or (body.role_code is not None and body.role_code != "admin")
    ):
        raise AppError("不能停用或降权自己", code=400, status_code=400)
    user = await auth_service.update_user(db, user_id, body)
    return ok(UserOut.model_validate(user).model_dump(mode="json"))
