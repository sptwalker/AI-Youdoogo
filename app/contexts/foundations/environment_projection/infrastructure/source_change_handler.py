"""Outbox adapter for Environment Projection source-change notifications."""

from __future__ import annotations

import asyncio

from app.contexts.foundations.environment_projection.application.invalidation import (
    EnvironmentInvalidationState,
    InvalidateEnvironmentSnapshot,
    InvalidationResult,
    SnapshotCachePort,
    SnapshotRefreshPort,
)
from app.contexts.foundations.environment_projection.contracts.source_change import (
    EnvironmentSourceChange,
)
from app.platform.outbox.model import OutboxEvent

_state = EnvironmentInvalidationState()
_lock = asyncio.Lock()


async def handle_source_change(
    event: OutboxEvent,
    *,
    cache: SnapshotCachePort,
    refresh: SnapshotRefreshPort,
) -> InvalidationResult:
    """Consume once per newest revision, then rebuild the existing document projection."""
    contract = EnvironmentSourceChange.from_wire(
        event_id=event.id,
        event_type=event.event_type,
        payload=event.payload,
    )
    async with _lock:
        result = InvalidateEnvironmentSnapshot(state=_state, cache=cache).execute(contract)
        if not result.applied:
            return result
        try:
            await refresh.refresh()
        except Exception:
            _state.rollback(contract, previous_version=result.previous_version)
            raise
        return result


def reset_invalidation_state() -> None:
    """Test seam; production state naturally resets with the process."""
    _state.reset()
