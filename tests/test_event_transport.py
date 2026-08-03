"""Reliable-event contracts model duplicate delivery, DLQ evidence, and replay."""

from datetime import UTC, datetime, timedelta

import pytest

from app.platform.event_transport import (
    DeliveryFailure,
    EventEnvelope,
    InMemoryDeadLetterStore,
    InMemoryEventInbox,
    InMemoryEventPublisher,
    InMemoryEventReplayer,
    ReplayRequest,
)


def _event(now: datetime) -> EventEnvelope:
    return EventEnvelope.new(
        event_id="event-1",
        event_type="knowledge.document.indexed",
        schema_version=1,
        occurred_at=now,
        producer="knowledge-service",
        payload={"document_id": "doc-1"},
        correlation_id="request-1",
    )


def test_envelope_rejects_unversioned_or_naive_events() -> None:
    now = datetime.now(UTC)
    with pytest.raises(ValueError, match="schema_version"):
        EventEnvelope.new(
            event_type="test.event",
            producer="test",
            payload={},
            schema_version=0,
            occurred_at=now,
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        EventEnvelope.new(
            event_type="test.event",
            producer="test",
            payload={},
            occurred_at=now.replace(tzinfo=None),
        )


@pytest.mark.asyncio
async def test_inbox_deduplicates_active_and_completed_deliveries() -> None:
    now = datetime.now(UTC)
    event = _event(now)
    inbox = InMemoryEventInbox()
    first = await inbox.claim(
        event,
        consumer_id="search-projection",
        claimed_at=now,
        lease_until=now + timedelta(seconds=30),
    )
    assert first is not None
    assert await inbox.claim(
        event,
        consumer_id="search-projection",
        claimed_at=now + timedelta(seconds=1),
        lease_until=now + timedelta(seconds=31),
    ) is None

    second = await inbox.claim(
        event,
        consumer_id="search-projection",
        claimed_at=now + timedelta(seconds=31),
        lease_until=now + timedelta(seconds=61),
    )
    assert second is not None
    assert second.attempt == 2
    assert await inbox.complete(first, completed_at=now + timedelta(seconds=32)) is False
    assert await inbox.complete(second, completed_at=now + timedelta(seconds=33)) is True
    assert await inbox.was_processed(consumer_id="search-projection", event_id=event.event_id)
    assert await inbox.claim(
        event,
        consumer_id="search-projection",
        claimed_at=now + timedelta(seconds=62),
        lease_until=now + timedelta(seconds=92),
    ) is None


@pytest.mark.asyncio
async def test_failure_release_allows_retry_with_next_attempt() -> None:
    now = datetime.now(UTC)
    event = _event(now)
    inbox = InMemoryEventInbox()
    claim = await inbox.claim(
        event,
        consumer_id="search-projection",
        claimed_at=now,
        lease_until=now + timedelta(seconds=30),
    )
    assert claim is not None
    failure = DeliveryFailure.new(
        envelope=event,
        consumer_id="search-projection",
        attempt=1,
        failed_at=now + timedelta(seconds=1),
        error_code="dependency_timeout",
        error_message="index backend timed out",
        retryable=True,
        retry_at=now + timedelta(seconds=10),
    )
    assert await inbox.release(claim, failure=failure) is True

    assert await inbox.claim(
        event,
        consumer_id="search-projection",
        claimed_at=now + timedelta(seconds=2),
        lease_until=now + timedelta(seconds=32),
    ) is None

    retry = await inbox.claim(
        event,
        consumer_id="search-projection",
        claimed_at=now + timedelta(seconds=10),
        lease_until=now + timedelta(seconds=40),
    )
    assert retry is not None
    assert retry.attempt == 2


@pytest.mark.asyncio
async def test_inbox_rejects_expired_completion_and_terminal_retry() -> None:
    now = datetime.now(UTC)
    event = _event(now)
    inbox = InMemoryEventInbox()
    claim = await inbox.claim(
        event,
        consumer_id="search-projection",
        claimed_at=now,
        lease_until=now + timedelta(seconds=30),
    )
    assert claim is not None
    assert await inbox.complete(claim, completed_at=now + timedelta(seconds=30)) is False

    terminal = DeliveryFailure.new(
        envelope=event,
        consumer_id="search-projection",
        attempt=1,
        failed_at=now + timedelta(seconds=1),
        error_code="invalid_payload",
        error_message="event cannot be handled",
        retryable=False,
    )
    assert await inbox.release(claim, failure=terminal) is True
    assert await inbox.claim(
        event,
        consumer_id="search-projection",
        claimed_at=now + timedelta(seconds=31),
        lease_until=now + timedelta(seconds=61),
    ) is None


@pytest.mark.asyncio
async def test_dead_letter_is_idempotent_and_replay_preserves_event_id() -> None:
    now = datetime.now(UTC)
    event = _event(now)
    failure = DeliveryFailure.new(
        envelope=event,
        consumer_id="search-projection",
        attempt=5,
        failed_at=now,
        error_code="retry_exhausted",
        error_message="five attempts failed",
        retryable=False,
    )
    store = InMemoryDeadLetterStore()
    first = await store.put(failure, stored_at=now)
    second = await store.put(failure, stored_at=now + timedelta(seconds=1))
    assert first == second
    assert await store.pending() == (first,)

    publisher = InMemoryEventPublisher()
    replayer = InMemoryEventReplayer(store=store, publisher=publisher)
    request = ReplayRequest.new(
        dead_letter_id=first.dead_letter_id,
        requested_by="operator:42",
        requested_at=now + timedelta(minutes=1),
        reason="dependency recovered",
    )
    replayed = await replayer.replay(request)

    assert replayed.event_id == event.event_id
    assert publisher.published == (event,)
    updated = await store.get(first.dead_letter_id)
    assert updated is not None
    assert updated.replay_count == 1
    assert updated.last_replayed_at is not None
