"""用户管理接口（仅 admin）。"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, require_roles
from app.core.database import get_db
from app.core.exceptions import AppError, ok
from app.models.system import SysUser
from app.schemas.auth import UserCreate, UserOut, UserUpdate
from app.services import audit_service, auth_service

router = APIRouter(prefix="/users", tags=["users"])

DB = Annotated[AsyncSession, Depends(get_db)]
AdminUser = Annotated[SysUser, Depends(require_roles("admin"))]


@router.get("/roster")
async def roster(db: DB, _: CurrentUser) -> dict:
    """同事花名册（任意登录用户可读）：id + 姓名 + 部门，供群聊选人（I4）。"""
    users = await auth_service.list_users(db)
    return ok([
        {
            "id": str(u.id), "real_name": u.real_name, "en_name": u.en_name,
            "username": u.username, "title": u.title,
            "department_id": str(u.department_id) if u.department_id else None,
        }
        for u in users if u.is_active
    ])


@router.post("")
async def create_user(body: UserCreate, db: DB, admin: AdminUser) -> dict:
    """创建用户。"""
    user = await auth_service.create_user(db, body)
    await audit_service.audit(
        db, actor_id=admin.id, actor_role=admin.role_code, action="user.create",
        summary=f"创建用户 {user.username}（{user.role_code}）",
        target_type="sys_user", target_id=user.id,
    )
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
    await audit_service.audit(
        db, actor_id=admin.id, actor_role=admin.role_code, action="user.update",
        summary=f"更新用户 {user.username}",
        target_type="sys_user", target_id=user.id,
        detail={"role_code": body.role_code, "is_active": body.is_active},
    )
    return ok(UserOut.model_validate(user).model_dump(mode="json"))
