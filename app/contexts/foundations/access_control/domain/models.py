"""Access Control grant state independent from SQLAlchemy."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from app.contexts.shared_kernel import RuleViolation


class GranteeType(StrEnum):
    USER = "user"
    AGENT = "agent"
    DEPARTMENT = "department"


class PermissionLevel(StrEnum):
    READ = "read"
    WRITE = "write"
    ADMIN = "admin"


VALID_RESOURCE_TYPES = ("knowledge_base", "data_source")


def validate_resource_type(value: str) -> str:
    if value not in VALID_RESOURCE_TYPES:
        raise RuleViolation(
            f"resource_type 仅支持 {'/'.join(VALID_RESOURCE_TYPES)}"
        )
    return value


def validate_grantee_type(value: str) -> GranteeType:
    try:
        return GranteeType(value)
    except ValueError as exc:
        allowed = "/".join(item.value for item in GranteeType)
        raise RuleViolation(f"grantee_type 仅支持 {allowed}") from exc


def validate_permission(value: str) -> PermissionLevel:
    try:
        return PermissionLevel(value)
    except ValueError as exc:
        allowed = "/".join(item.value for item in PermissionLevel)
        raise RuleViolation(f"perm 仅支持 {allowed}") from exc


def _naive(value: datetime) -> datetime:
    return value.replace(tzinfo=None) if value.tzinfo else value


@dataclass(frozen=True, slots=True)
class GrantTarget:
    grantee_type: GranteeType
    grantee_id: uuid.UUID


@dataclass(slots=True)
class ResourceGrantRecord:
    id: uuid.UUID
    resource_type: str
    resource_id: uuid.UUID
    grantee_type: GranteeType
    grantee_id: uuid.UUID
    permission: PermissionLevel
    granted_by: uuid.UUID | None
    expires_at: datetime | None
    create_time: datetime
    is_deleted: bool = False

    def is_effective_at(self, now: datetime) -> bool:
        return not self.is_deleted and (
            self.expires_at is None or _naive(self.expires_at) > _naive(now)
        )

    def revoke(self) -> None:
        self.is_deleted = True
