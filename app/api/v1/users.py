"""用户管理接口（仅 admin）。"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, require_roles
from app.contexts.foundations.governance.audit_trail.public import (
    AppendAuditRecordCommand,
    append_audit_record,
)
from app.contexts.foundations.identity import public as identity
from app.contexts.foundations.identity.public import IdentityUserResult
from app.contexts.shared_kernel import InvalidInput
from app.platform.database import get_db
from app.platform.http_runtime import ok
from app.schemas.auth import AdminUserOut, UserCreate, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])

DB = Annotated[AsyncSession, Depends(get_db)]
AdminUser = Annotated[IdentityUserResult, Depends(require_roles("admin"))]


@router.get("/roster")
async def roster(db: DB, _: CurrentUser) -> dict:
    """同事花名册（任意登录用户可读）：id + 姓名 + 部门，供群聊选人（I4）。"""
    users = await identity.list_users(db)
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
    user = await identity.create_user(
        db,
        username=body.username,
        password=body.password,
        real_name=body.real_name,
        role_code=body.role_code,
        department_id=body.department_id,
        feishu_open_id=body.feishu_open_id,
    )
    await append_audit_record(
        db,
        AppendAuditRecordCommand(
            actor_id=admin.id,
            actor_role=admin.role_code,
            action="user.create",
            summary=f"创建用户 {user.username}（{user.role_code}）",
            target_type="sys_user",
            target_id=user.id,
        ),
    )
    return ok(AdminUserOut.model_validate(user).model_dump(mode="json"))


@router.get("")
async def list_users(db: DB, _: AdminUser) -> dict:
    """用户列表。"""
    users = await identity.list_users(db)
    return ok([AdminUserOut.model_validate(u).model_dump(mode="json") for u in users])


@router.patch("/{user_id}")
async def update_user(user_id: uuid.UUID, body: UserUpdate, db: DB, admin: AdminUser) -> dict:
    """更新用户（改密/停用/角色/部门）。禁止停用或降权自己，防 admin 自锁。"""
    if user_id == admin.id and (
        body.is_active is False or (body.role_code is not None and body.role_code != "admin")
    ):
        raise InvalidInput("不能停用或降权自己")
    user = await identity.update_user(
        db,
        user_id=user_id,
        password=body.password,
        real_name=body.real_name,
        role_code=body.role_code,
        department_id=body.department_id,
        is_active=body.is_active,
        feishu_open_id=body.feishu_open_id,
        feishu_binding_changed="feishu_open_id" in body.model_fields_set,
    )
    await append_audit_record(
        db,
        AppendAuditRecordCommand(
            actor_id=admin.id,
            actor_role=admin.role_code,
            action="user.update",
            summary=f"更新用户 {user.username}",
            target_type="sys_user",
            target_id=user.id,
            detail={
                "role_code": body.role_code,
                "is_active": body.is_active,
                "feishu_binding_changed": "feishu_open_id" in body.model_fields_set,
            },
        ),
    )
    return ok(AdminUserOut.model_validate(user).model_dump(mode="json"))
