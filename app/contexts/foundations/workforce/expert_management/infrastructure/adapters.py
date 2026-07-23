"""Expert Management platform adapters."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

import app.platform.outbox.source_change as source_change_events


class ExpertSourceChangeAdapter:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def publish_expert_changed(self, expert_id: uuid.UUID) -> None:
        await source_change_events.publish_source_change(
            self._session,
            source_type="expert",
            source_id=expert_id,
            affected_scopes=("expert",),
        )


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class UUIDIdentifier:
    def new_id(self) -> uuid.UUID:
        return uuid.uuid4()
