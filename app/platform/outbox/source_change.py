"""Transactional publication of source facts consumed by read-model projections."""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

import app.platform.outbox.repository as outbox_repository
from app.platform.outbox.model import OutboxEvent

ENVIRONMENT_SOURCE_CHANGED_V1 = "environment.source.changed.v1"
DEFAULT_TENANT_ID = "default"

_last_source_versions: dict[tuple[str, uuid.UUID], int] = {}


def _next_source_version(source_type: str, source_id: uuid.UUID) -> int:
    """Return a process-monotonic revision without requiring a schema change."""
    key = (source_type, source_id)
    version = max(time.time_ns(), _last_source_versions.get(key, 0) + 1)
    _last_source_versions[key] = version
    return version


async def publish_source_change(
    db: AsyncSession,
    *,
    source_type: str,
    source_id: uuid.UUID,
    affected_scopes: tuple[str, ...],
    tenant_id: str = DEFAULT_TENANT_ID,
    source_version: int | None = None,
    occurred_at: datetime | None = None,
) -> OutboxEvent:
    """Append a versioned source-change event in the caller's transaction."""
    event_id = uuid.uuid4()
    version = source_version or _next_source_version(source_type, source_id)
    changed_at = occurred_at or datetime.now(UTC)
    return await outbox_repository.enqueue(
        db,
        event_id=event_id,
        aggregate_type="environment_source",
        aggregate_id=source_id,
        event_type=ENVIRONMENT_SOURCE_CHANGED_V1,
        dedupe_key=f"environment-source:{source_type}:{source_id}:v{version}",
        payload={
            "event_id": str(event_id),
            "event_type": ENVIRONMENT_SOURCE_CHANGED_V1,
            "tenant_id": tenant_id,
            "source_type": source_type,
            "source_id": str(source_id),
            "source_version": version,
            "occurred_at": changed_at.isoformat(),
            "scope": list(affected_scopes),
        },
    )
