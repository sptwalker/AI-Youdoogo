"""In-memory test adapters; intentionally absent from production composition."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from app.platform.event_transport.contracts import (
    DeadLetterRecord,
    DeliveryFailure,
    EventEnvelope,
    InboxClaim,
    ReplayRequest,
)
from app.platform.event_transport.ports import DeadLetterStore, EventPublisher


class InMemoryEventPublisher:
    """Capture published envelopes for fast contract and use-case tests."""

    def __init__(self) -> None:
        self._published: list[EventEnvelope] = []
        self._lock = asyncio.Lock()

    @property
    def published(self) -> tuple[EventEnvelope, ...]:
        """Return a read-only snapshot of captured events."""
        return tuple(self._published)

    async def publish(self, envelope: EventEnvelope) -> None:
        """Capture every call, including duplicate event identifiers."""
        async with self._lock:
            self._published.append(envelope)


@dataclass(slots=True)
class _InboxEntry:
    attempt: int
    active_claim: InboxClaim | None = None
    completed_at: datetime | None = None
    last_failure: DeliveryFailure | None = None


class InMemoryEventInbox:
    """Model lease expiry and exactly-once effects over at-least-once delivery."""

    def __init__(self) -> None:
        self._entries: dict[tuple[str, str], _InboxEntry] = {}
        self._lock = asyncio.Lock()

    async def claim(
        self,
        envelope: EventEnvelope,
        *,
        consumer_id: str,
        claimed_at: datetime,
        lease_until: datetime,
    ) -> InboxClaim | None:
        """Return None for completed or currently leased duplicate deliveries."""
        key = (consumer_id, envelope.event_id)
        async with self._lock:
            entry = self._entries.get(key)
            if entry is not None and entry.completed_at is not None:
                return None
            if (
                entry is not None
                and entry.active_claim is not None
                and entry.active_claim.lease_until > claimed_at
            ):
                return None
            if entry is not None and entry.last_failure is not None:
                failure = entry.last_failure
                if not failure.retryable:
                    return None
                if failure.retry_at is not None and failure.retry_at > claimed_at:
                    return None
            attempt = 1 if entry is None else entry.attempt + 1
            claim = InboxClaim(
                event_id=envelope.event_id,
                consumer_id=consumer_id,
                claim_id=str(uuid.uuid4()),
                attempt=attempt,
                claimed_at=claimed_at,
                lease_until=lease_until,
            )
            if entry is None:
                self._entries[key] = _InboxEntry(attempt=attempt, active_claim=claim)
            else:
                entry.attempt = attempt
                entry.active_claim = claim
            return claim

    async def complete(self, claim: InboxClaim, *, completed_at: datetime) -> bool:
        """Complete only the current lease token; stale workers cannot win."""
        if completed_at.tzinfo is None or completed_at.utcoffset() is None:
            raise ValueError("completed_at must be timezone-aware")
        if completed_at < claim.claimed_at:
            raise ValueError("completed_at must not be earlier than claimed_at")
        key = (claim.consumer_id, claim.event_id)
        async with self._lock:
            entry = self._entries.get(key)
            if (
                entry is None
                or entry.active_claim != claim
                or completed_at >= claim.lease_until
            ):
                return False
            entry.active_claim = None
            entry.completed_at = completed_at
            return True

    async def release(self, claim: InboxClaim, *, failure: DeliveryFailure) -> bool:
        """Release the current attempt for retry after recording failure evidence."""
        if failure.envelope.event_id != claim.event_id:
            raise ValueError("failure event does not match inbox claim")
        if failure.consumer_id != claim.consumer_id or failure.attempt != claim.attempt:
            raise ValueError("failure consumer/attempt does not match inbox claim")
        if failure.failed_at < claim.claimed_at:
            raise ValueError("failure cannot predate the inbox claim")
        key = (claim.consumer_id, claim.event_id)
        async with self._lock:
            entry = self._entries.get(key)
            if (
                entry is None
                or entry.active_claim != claim
                or failure.failed_at >= claim.lease_until
            ):
                return False
            entry.active_claim = None
            entry.last_failure = failure
            return True

    async def was_processed(self, *, consumer_id: str, event_id: str) -> bool:
        """Test-only observation seam for completed idempotency records."""
        async with self._lock:
            entry = self._entries.get((consumer_id, event_id))
            return entry is not None and entry.completed_at is not None


class InMemoryDeadLetterStore:
    """Retain dead letters and replay counters without persistence or a broker."""

    def __init__(self) -> None:
        self._records: dict[str, DeadLetterRecord] = {}
        self._failure_index: dict[str, str] = {}
        self._lock = asyncio.Lock()

    async def put(
        self,
        failure: DeliveryFailure,
        *,
        stored_at: datetime,
    ) -> DeadLetterRecord:
        """Store each failure once so adapter retries do not duplicate dead letters."""
        async with self._lock:
            existing_id = self._failure_index.get(failure.failure_id)
            if existing_id is not None:
                return self._records[existing_id]
            record = DeadLetterRecord(
                dead_letter_id=str(uuid.uuid4()),
                failure=failure,
                stored_at=stored_at,
            )
            self._records[record.dead_letter_id] = record
            self._failure_index[failure.failure_id] = record.dead_letter_id
            return record

    async def get(self, dead_letter_id: str) -> DeadLetterRecord | None:
        """Return a retained record by identifier."""
        async with self._lock:
            return self._records.get(dead_letter_id)

    async def pending(self, *, limit: int = 100) -> tuple[DeadLetterRecord, ...]:
        """Return oldest records first, including replay history for operators."""
        if limit < 1:
            raise ValueError("limit must be at least 1")
        async with self._lock:
            records = sorted(self._records.values(), key=lambda record: record.stored_at)
            return tuple(records[:limit])

    async def record_replay(
        self,
        request: ReplayRequest,
        *,
        replayed_at: datetime,
    ) -> DeadLetterRecord:
        """Atomically increment replay history for an existing dead letter."""
        async with self._lock:
            record = self._records.get(request.dead_letter_id)
            if record is None:
                raise KeyError(request.dead_letter_id)
            updated = record.mark_replayed(replayed_at)
            self._records[record.dead_letter_id] = updated
            return updated


class InMemoryEventReplayer:
    """Test adapter proving replay preserves event_id and publishes before marking."""

    def __init__(self, *, store: DeadLetterStore, publisher: EventPublisher) -> None:
        self._store = store
        self._publisher = publisher

    async def replay(self, request: ReplayRequest) -> EventEnvelope:
        """Republish the original envelope and record successful replay evidence."""
        record = await self._store.get(request.dead_letter_id)
        if record is None:
            raise KeyError(request.dead_letter_id)
        await self._publisher.publish(record.failure.envelope)
        await self._store.record_replay(request, replayed_at=datetime.now(UTC))
        return record.failure.envelope
