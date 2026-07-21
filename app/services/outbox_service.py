"""事务性 outbox：入队、租约抢占、完成与退避重试。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.workflow import (
    OUTBOX_DONE,
    OUTBOX_FAILED,
    OUTBOX_PENDING,
    OUTBOX_PROCESSING,
    OutboxEvent,
)


def utcnow() -> datetime:
    """返回带 UTC 时区的当前时间，集中避免 worker 时间口径漂移。"""
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
    """在调用方事务中追加 outbox；同一 dedupe_key 已存在时复用。"""
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
        # 多 worker 同时根据同一状态计算 ready step 时，唯一 dedupe key 收敛重复入队。
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
    """抢占一条可用事件；PostgreSQL 用 SKIP LOCKED，更新时再做状态条件保护。"""
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
    """仅当前租约持有者可把事件标记完成。"""
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


async def defer(
    db: AsyncSession,
    event: OutboxEvent,
    *,
    worker_id: str,
    available_at: datetime,
    reason: str | None = None,
) -> bool:
    """释放当前事件租约并延迟重试；busy defer 不消耗失败重试次数。"""
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
    """记录失败；未耗尽次数则退避回 pending，否则进入 failed 终态。"""
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
