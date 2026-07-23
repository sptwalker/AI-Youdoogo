"""Application-owned query and evidence contracts."""

from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ConnectorQueryConfiguration:
    base_url: str
    api_secret: str


@dataclass(frozen=True, slots=True)
class QueryAuditEvidence:
    actor_id: uuid.UUID | None
    actor_role: str | None
    sql: str
    source: str
    result: str
    detail: dict[str, object]
