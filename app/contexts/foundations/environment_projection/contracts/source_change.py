"""Published language accepted by the Environment Projection consumer."""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

ENVIRONMENT_SOURCE_CHANGED_V1 = "environment.source.changed.v1"


@dataclass(frozen=True, slots=True)
class EnvironmentSourceChange:
    """Immutable, versioned notification that a source-owned fact changed."""

    event_id: uuid.UUID
    event_type: str
    tenant_id: str
    source_type: str
    source_id: uuid.UUID
    source_version: int
    occurred_at: datetime
    affected_scopes: tuple[str, ...]

    @classmethod
    def from_wire(
        cls,
        *,
        event_id: uuid.UUID,
        event_type: str,
        payload: Mapping[str, object],
    ) -> EnvironmentSourceChange:
        """Validate and translate a transport payload at the adapter boundary."""
        if event_type != ENVIRONMENT_SOURCE_CHANGED_V1:
            raise ValueError(f"unsupported environment source event: {event_type}")
        payload_event_type = str(payload.get("event_type", ""))
        if payload_event_type != event_type:
            raise ValueError("environment source event_type mismatch")
        payload_event_id = uuid.UUID(str(payload.get("event_id", "")))
        if payload_event_id != event_id:
            raise ValueError("environment source event_id mismatch")
        tenant_id = str(payload.get("tenant_id", ""))
        source_type = str(payload.get("source_type", ""))
        if not tenant_id or not source_type:
            raise ValueError("environment source event is missing ownership metadata")
        source_version = int(str(payload.get("source_version", "0")))
        if source_version <= 0:
            raise ValueError("environment source_version must be positive")
        occurred_at = datetime.fromisoformat(str(payload.get("occurred_at", "")))
        if occurred_at.tzinfo is None:
            raise ValueError("environment occurred_at must include a timezone")
        raw_scope = payload.get("scope", ())
        if not isinstance(raw_scope, Sequence) or isinstance(raw_scope, (str, bytes)):
            raise ValueError("environment scope must be a sequence")
        scopes = tuple(str(item) for item in raw_scope if str(item))
        if not scopes:
            raise ValueError("environment source event requires an affected scope")
        return cls(
            event_id=event_id,
            event_type=event_type,
            tenant_id=tenant_id,
            source_type=source_type,
            source_id=uuid.UUID(str(payload.get("source_id", ""))),
            source_version=source_version,
            occurred_at=occurred_at,
            affected_scopes=scopes,
        )
