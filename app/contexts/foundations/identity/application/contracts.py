"""Plain Identity commands and results."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from app.contexts.foundations.identity.contracts import Principal


@dataclass(frozen=True, slots=True)
class AuthenticatePasswordCommand:
    username: str
    password: str


@dataclass(frozen=True, slots=True)
class AuthenticateFeishuCommand:
    open_id: str


@dataclass(frozen=True, slots=True)
class LoginByFeishuCommand:
    code: str


@dataclass(frozen=True, slots=True)
class ResolvePrincipalQuery:
    user_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class CreateUserCommand:
    username: str
    password: str
    real_name: str = ""
    role_code: str = "member"
    department_id: uuid.UUID | None = None
    feishu_open_id: str | None = None


@dataclass(frozen=True, slots=True)
class UpdateUserCommand:
    user_id: uuid.UUID
    password: str | None = None
    real_name: str | None = None
    role_code: str | None = None
    department_id: uuid.UUID | None = None
    is_active: bool | None = None
    feishu_open_id: str | None = None
    feishu_binding_changed: bool = False


@dataclass(frozen=True, slots=True)
class SyncExternalUserCommand:
    """Authoritative profile received from the Feishu directory."""

    feishu_open_id: str
    real_name: str
    en_name: str = ""
    title: str = ""
    mobile: str = ""
    avatar_url: str = ""
    department_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class IdentityUserResult:
    """Public user shape compatible with current response models and facades."""

    id: uuid.UUID
    username: str
    real_name: str
    role_code: str
    department_id: uuid.UUID | None
    is_active: bool
    feishu_open_id: str | None
    en_name: str
    title: str
    mobile: str
    avatar_url: str
    create_time: datetime
    is_delete: bool = False


@dataclass(frozen=True, slots=True)
class AuthenticatedIdentity:
    principal: Principal
    user: IdentityUserResult


@dataclass(frozen=True, slots=True)
class ExternalUserSyncResult:
    user: IdentityUserResult
    created: bool
