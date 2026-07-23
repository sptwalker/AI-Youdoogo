"""Idempotent Environment Projection invalidation use case."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol

from app.contexts.foundations.environment_projection.contracts.source_change import (
    EnvironmentSourceChange,
)


class SnapshotCachePort(Protocol):
    """Environment-owned cache operation required by invalidation."""

    def invalidate(self) -> None: ...


class SnapshotRefreshPort(Protocol):
    """Outer refresh operation invoked after an accepted invalidation."""

    async def refresh(self) -> None: ...


@dataclass(frozen=True, slots=True)
class InvalidationResult:
    applied: bool
    reason: str
    source_version: int
    previous_version: int = 0


class EnvironmentInvalidationState:
    """Track processed event identities and monotonic source revisions."""

    def __init__(self) -> None:
        self._seen_event_ids: set[uuid.UUID] = set()
        self._source_versions: dict[tuple[str, str, uuid.UUID], int] = {}

    def apply(self, event: EnvironmentSourceChange) -> InvalidationResult:
        if event.event_id in self._seen_event_ids:
            return InvalidationResult(False, "duplicate", event.source_version)
        self._seen_event_ids.add(event.event_id)
        source_key = (event.tenant_id, event.source_type, event.source_id)
        current_version = self._source_versions.get(source_key, 0)
        if event.source_version <= current_version:
            return InvalidationResult(False, "stale", event.source_version)
        self._source_versions[source_key] = event.source_version
        return InvalidationResult(
            True,
            "applied",
            event.source_version,
            previous_version=current_version,
        )

    def rollback(self, event: EnvironmentSourceChange, *, previous_version: int) -> None:
        """Forget a provisional application when the outer refresh fails."""
        source_key = (event.tenant_id, event.source_type, event.source_id)
        if self._source_versions.get(source_key) == event.source_version:
            if previous_version > 0:
                self._source_versions[source_key] = previous_version
            else:
                self._source_versions.pop(source_key, None)
        self._seen_event_ids.discard(event.event_id)

    def reset(self) -> None:
        """Reset process-local state for deterministic adapter tests."""
        self._seen_event_ids.clear()
        self._source_versions.clear()


class InvalidateEnvironmentSnapshot:
    """Invalidate a snapshot once for each newest source revision."""

    def __init__(self, *, state: EnvironmentInvalidationState, cache: SnapshotCachePort) -> None:
        self._state = state
        self._cache = cache

    def execute(self, event: EnvironmentSourceChange) -> InvalidationResult:
        result = self._state.apply(event)
        if result.applied:
            self._cache.invalidate()
        return result
