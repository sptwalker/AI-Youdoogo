"""Access Control commands and stable result values."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class CreateGrantCommand:
    resource_type: str
    resource_id: uuid.UUID
    grantee_type: str
    grantee_id: uuid.UUID
    permission: str = "read"
    granted_by: uuid.UUID | None = None
    expires_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ListGrantsQuery:
    resource_type: str | None = None
    grantee_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class GrantResult:
    id: uuid.UUID
    resource_type: str
    resource_id: uuid.UUID
    grantee_type: str
    grantee_id: uuid.UUID
    perm: str
    granted_by: uuid.UUID | None
    expires_at: datetime | None
    create_time: datetime
