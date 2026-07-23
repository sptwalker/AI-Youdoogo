"""Request-scoped Identity operations used by compatibility callers."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.identity.application.contracts import (
    AuthenticateFeishuCommand,
    AuthenticatePasswordCommand,
    CreateUserCommand,
    ExternalUserSyncResult,
    IdentityUserResult,
    LoginByFeishuCommand,
    ResolvePrincipalQuery,
    SyncExternalUserCommand,
    UpdateUserCommand,
)
from app.contexts.foundations.identity.infrastructure.composition import (
    build_identity_application,
)


async def authenticate_password(
    session: AsyncSession,
    *,
    username: str,
    password: str,
) -> IdentityUserResult:
    authenticated = await build_identity_application(session).authenticate_password(
        AuthenticatePasswordCommand(username=username, password=password)
    )
    return authenticated.user


async def authenticate_feishu(
    session: AsyncSession,
    *,
    open_id: str,
) -> IdentityUserResult:
    authenticated = await build_identity_application(session).authenticate_feishu(
        AuthenticateFeishuCommand(open_id=open_id)
    )
    return authenticated.user


async def login_by_feishu(
    session: AsyncSession,
    *,
    code: str,
) -> IdentityUserResult:
    authenticated = await build_identity_application(session).login_by_feishu(
        LoginByFeishuCommand(code=code)
    )
    return authenticated.user


async def get_user_by_id(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
) -> IdentityUserResult | None:
    authenticated = await build_identity_application(session).resolve_principal(
        ResolvePrincipalQuery(user_id=user_id)
    )
    return authenticated.user if authenticated is not None else None


async def create_user(
    session: AsyncSession,
    *,
    username: str,
    password: str,
    real_name: str,
    role_code: str,
    department_id: uuid.UUID | None,
    feishu_open_id: str | None,
) -> IdentityUserResult:
    return await build_identity_application(session).create_user(
        CreateUserCommand(
            username=username,
            password=password,
            real_name=real_name,
            role_code=role_code,
            department_id=department_id,
            feishu_open_id=feishu_open_id,
        )
    )


async def list_users(session: AsyncSession) -> tuple[IdentityUserResult, ...]:
    return await build_identity_application(session).list_users()


async def sync_external_user(
    session: AsyncSession,
    command: SyncExternalUserCommand,
) -> ExternalUserSyncResult:
    return await build_identity_application(session).sync_external_user(command)


async def update_user(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    password: str | None,
    real_name: str | None,
    role_code: str | None,
    department_id: uuid.UUID | None,
    is_active: bool | None,
    feishu_open_id: str | None,
    feishu_binding_changed: bool,
) -> IdentityUserResult:
    return await build_identity_application(session).update_user(
        UpdateUserCommand(
            user_id=user_id,
            password=password,
            real_name=real_name,
            role_code=role_code,
            department_id=department_id,
            is_active=is_active,
            feishu_open_id=feishu_open_id,
            feishu_binding_changed=feishu_binding_changed,
        )
    )
