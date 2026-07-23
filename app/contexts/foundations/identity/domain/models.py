"""Identity account state and rules independent from persistence and delivery."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime

from app.contexts.shared_kernel import RuleViolation

VALID_ROLES = ("admin", "executive", "member")
_FEISHU_OPEN_ID = re.compile(r"^ou[-_][A-Za-z0-9_-]+$")


def validate_role(role_code: str) -> None:
    """Enforce the currently supported role dictionary."""
    if role_code not in VALID_ROLES:
        raise RuleViolation(f"非法角色：{role_code}，可选 {'/'.join(VALID_ROLES)}")


def valid_feishu_open_id(value: str) -> bool:
    """Validate the stable app-scoped Feishu identity key."""
    return 8 <= len(value) <= 128 and _FEISHU_OPEN_ID.fullmatch(value) is not None


@dataclass(slots=True)
class IdentityAccount:
    """Identity-owned account state mapped to the existing ``sys_user`` table."""

    id: uuid.UUID
    username: str
    password_hash: str
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
    is_deleted: bool = False

    def update(
        self,
        *,
        password_hash: str | None,
        real_name: str | None,
        role_code: str | None,
        department_id: uuid.UUID | None,
        is_active: bool | None,
        feishu_open_id: str | None,
        feishu_binding_changed: bool,
    ) -> None:
        """Apply the legacy partial-update contract without transport objects."""
        if role_code is not None:
            validate_role(role_code)
            self.role_code = role_code
        if password_hash is not None:
            self.password_hash = password_hash
        if real_name is not None:
            self.real_name = real_name
        # Existing API cannot clear department membership with null; preserve that behavior.
        if department_id is not None:
            self.department_id = department_id
        if is_active is not None:
            self.is_active = is_active
        if feishu_binding_changed:
            self.feishu_open_id = feishu_open_id

    def sync_external_profile(
        self,
        *,
        real_name: str,
        en_name: str,
        title: str,
        mobile: str,
        avatar_url: str,
        department_id: uuid.UUID | None,
    ) -> None:
        """Apply the latest external directory-owned profile fields."""
        self.real_name = real_name
        self.en_name = en_name
        self.title = title
        self.mobile = mobile
        self.avatar_url = avatar_url
        self.department_id = department_id
