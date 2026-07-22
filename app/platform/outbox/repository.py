"""Transactional outbox persistence, leasing, completion, and retry operations."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.outbox.model import (
    OUTBOX_DONE,
    OUTBOX_FAILED,
    OUTBOX_PENDING,
    OUTBOX_PROCESSING,
    OutboxEvent,
)


def utcnow() -> datetime:
    """Return a timezone-aware UTC timestamp for worker lease calculations."""
    return datetime.now(UTC)


async def enqueue(
    db: AsyncSession,
    *,
    aggregate_type: str,
    aggregate_id: uuid.UUID,
    event_type: str,
    dedupe_key: str,
    payload: dict[str, Any] | None = None,
    available_at: datetime | None = None,
    max_attempts: int = 5,
) -> OutboxEvent:
    """Append an event in the caller transaction, reusing an existing dedupe key."""
    existing = (
        await db.execute(select(OutboxEvent).where(OutboxEvent.dedupe_key == dedupe_key))
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    event = OutboxEvent(
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        event_type=event_type,
        dedupe_key=dedupe_key,
        payload=payload or {},
        available_at=available_at or utcnow(),
        max_attempts=max_attempts,
    )
    try:
        async with db.begin_nested():
            db.add(event)
            await db.flush()
    except IntegrityError:
        existing = (
            await db.execute(select(OutboxEvent).where(OutboxEvent.dedupe_key == dedupe_key))
        ).scalar_one()
        return existing
    return event


async def claim_next(
    db: AsyncSession,
    *,
    worker_id: str,
    lease_seconds: int,
) -> OutboxEvent | None:
    """Claim one available event, using SKIP LOCKED on PostgreSQL."""
    now = utcnow()
    claimable = or_(
        and_(OutboxEvent.status == OUTBOX_PENDING, OutboxEvent.available_at <= now),
        and_(OutboxEvent.status == OUTBOX_PROCESSING, OutboxEvent.lease_until < now),
    )
    stmt = (
        select(OutboxEvent)
        .where(OutboxEvent.is_delete.is_(False), claimable)
        .order_by(OutboxEvent.available_at, OutboxEvent.create_time)
        .limit(1)
    )
    if db.get_bind().dialect.name == "postgresql":
        stmt = stmt.with_for_update(skip_locked=True)
    candidate = (await db.execute(stmt)).scalar_one_or_none()
    if candidate is None:
        return None
    claimed = await db.execute(
        update(OutboxEvent)
        .where(OutboxEvent.id == candidate.id, claimable)
        .values(
            status=OUTBOX_PROCESSING,
            attempts=OutboxEvent.attempts + 1,
            lease_owner=worker_id,
            lease_until=now + timedelta(seconds=lease_seconds),
            last_error=None,
        )
        .execution_options(synchronize_session=False)
    )
    if getattr(claimed, "rowcount", 0) != 1:
        return None
    await db.flush()
    await db.refresh(candidate)
    return candidate


async def complete(db: AsyncSession, event: OutboxEvent, *, worker_id: str) -> bool:
    """Mark an event complete only when the caller owns its active lease."""
    result = await db.execute(
        update(OutboxEvent)
        .where(
            OutboxEvent.id == event.id,
            OutboxEvent.status == OUTBOX_PROCESSING,
            OutboxEvent.lease_owner == worker_id,
        )
        .values(status=OUTBOX_DONE, lease_owner=None, lease_until=None, last_error=None)
        .execution_options(synchronize_session=False)
    )
    await db.flush()
    return getattr(result, "rowcount", 0) == 1


async def renew_lease(
    db: AsyncSession,
    event_id: uuid.UUID,
    *,
    worker_id: str,
    lease_seconds: int,
) -> bool:
    """Extend the lease only for its current processing owner."""
    result = await db.execute(
        update(OutboxEvent)
        .where(
            OutboxEvent.id == event_id,
            OutboxEvent.status == OUTBOX_PROCESSING,
            OutboxEvent.lease_owner == worker_id,
        )
        .values(lease_until=utcnow() + timedelta(seconds=lease_seconds))
        .execution_options(synchronize_session=False)
    )
    await db.flush()
    return getattr(result, "rowcount", 0) == 1


async def defer(
    db: AsyncSession,
    event: OutboxEvent,
    *,
    worker_id: str,
    available_at: datetime,
    reason: str | None = None,
) -> bool:
    """Release the current lease and postpone work without consuming an attempt."""
    now = utcnow()
    if available_at.tzinfo is None:
        available_at = available_at.replace(tzinfo=UTC)
    result = await db.execute(
        update(OutboxEvent)
        .where(
            OutboxEvent.id == event.id,
            OutboxEvent.status == OUTBOX_PROCESSING,
            OutboxEvent.lease_owner == worker_id,
        )
        .values(
            status=OUTBOX_PENDING,
            attempts=OutboxEvent.attempts - 1,
            available_at=max(available_at, now),
            lease_owner=None,
            lease_until=None,
            last_error=reason[:2000] if reason else None,
        )
        .execution_options(synchronize_session=False)
    )
    await db.flush()
    return getattr(result, "rowcount", 0) == 1


async def fail(
    db: AsyncSession,
    event: OutboxEvent,
    *,
    worker_id: str,
    error: str,
    retry_delay_seconds: int,
) -> bool:
    """Record a failure and either retry later or enter the failed terminal state."""
    terminal = event.attempts >= event.max_attempts
    values: dict[str, Any] = {
        "status": OUTBOX_FAILED if terminal else OUTBOX_PENDING,
        "lease_owner": None,
        "lease_until": None,
        "last_error": error[:2000],
    }
    if not terminal:
        values["available_at"] = utcnow() + timedelta(seconds=retry_delay_seconds)
    result = await db.execute(
        update(OutboxEvent)
        .where(
            OutboxEvent.id == event.id,
            OutboxEvent.status == OUTBOX_PROCESSING,
            OutboxEvent.lease_owner == worker_id,
        )
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    await db.flush()
    return getattr(result, "rowcount", 0) == 1
