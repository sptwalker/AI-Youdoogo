"""Compatibility facade delegating Identity behavior to its bounded context."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.identity.entrypoints import operations
from app.schemas.auth import UserCreate, UserUpdate

if TYPE_CHECKING:
    from app.models.system import SysUser


async def authenticate(db: AsyncSession, username: str, password: str) -> SysUser:
    """Authenticate a local user while preserving the legacy callable shape."""
    result = await operations.authenticate_password(
        db,
        username=username,
        password=password,
    )
    return cast("SysUser", result)


async def authenticate_feishu(db: AsyncSession, open_id: str) -> SysUser:
    """Authenticate one pre-bound Feishu identity without provisioning."""
    result = await operations.authenticate_feishu(db, open_id=open_id)
    return cast("SysUser", result)


async def get_user_by_id(db: AsyncSession, user_id: uuid.UUID) -> SysUser | None:
    """Resolve an active or inactive, non-deleted user by identifier."""
    result = await operations.get_user_by_id(db, user_id=user_id)
    return cast("SysUser | None", result)


async def login_by_feishu(db: AsyncSession, code: str) -> SysUser:
    """Exchange a Feishu callback code and authenticate the bound user."""
    result = await operations.login_by_feishu(db, code=code)
    return cast("SysUser", result)


async def create_user(db: AsyncSession, data: UserCreate) -> SysUser:
    """Create a user through the Identity application boundary."""
    result = await operations.create_user(
        db,
        username=data.username,
        password=data.password,
        real_name=data.real_name,
        role_code=data.role_code,
        department_id=data.department_id,
        feishu_open_id=data.feishu_open_id,
    )
    return cast("SysUser", result)


async def list_users(db: AsyncSession) -> list[SysUser]:
    """List non-deleted users in creation order."""
    result = await operations.list_users(db)
    return cast("list[SysUser]", list(result))


async def update_user(db: AsyncSession, user_id: uuid.UUID, data: UserUpdate) -> SysUser:
    """Apply the current partial-update contract through Identity."""
    result = await operations.update_user(
        db,
        user_id=user_id,
        password=data.password,
        real_name=data.real_name,
        role_code=data.role_code,
        department_id=data.department_id,
        is_active=data.is_active,
        feishu_open_id=data.feishu_open_id,
        feishu_binding_changed="feishu_open_id" in data.model_fields_set,
    )
    return cast("SysUser", result)
