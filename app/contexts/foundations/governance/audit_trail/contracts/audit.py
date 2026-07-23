"""Framework-independent Audit Trail commands and views."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class AppendAuditRecordCommand:
    action: str
    summary: str
    actor_id: uuid.UUID | None = None
    actor_role: str | None = None
    target_type: str | None = None
    target_id: uuid.UUID | None = None
    detail: Mapping[str, object] | None = None
    result: str = "ok"


@dataclass(frozen=True, slots=True)
class AuditTrailQuery:
    action: str | None = None
    actor_id: uuid.UUID | None = None
    limit: int = 100


@dataclass(frozen=True, slots=True)
class AuditRecordView:
    record_id: uuid.UUID
    actor_id: uuid.UUID | None
    actor_role: str | None
    action: str
    target_type: str | None
    target_id: uuid.UUID | None
    summary: str
    detail: Mapping[str, object] | None
    result: str
    occurred_at: str


class AuditEvidencePort(Protocol):
    """Published append-only evidence operation for caller-owned adapters."""

    async def append(self, command: AppendAuditRecordCommand) -> None: ...
