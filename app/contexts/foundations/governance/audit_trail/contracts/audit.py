"""Framework-independent Audit Trail commands and views."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
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
    start: datetime | None = None
    end: datetime | None = None
    limit: int = 100
    offset: int = 0


@dataclass(frozen=True, slots=True)
class AuditTrailPage:
    """一页审计记录 + 满足筛选条件的总数（供前端服务端翻页）。"""

    items: tuple[AuditRecordView, ...]
    total: int


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
