"""Generic leased Outbox worker mechanics for Workflow Runtime."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.contexts.foundations.execution.workflow_runtime.contracts.runtime import (
    StepExecutionDisposition,
)
from app.models.workflow import OutboxEvent
from app.platform.outbox import repository as outbox

logger = logging.getLogger(__name__)
EventHandler = Callable[
    [AsyncSession, OutboxEvent, str], Awaitable[StepExecutionDisposition]
]
TerminalFailureHandler = Callable[[AsyncSession, OutboxEvent, str], Awaitable[None]]


async def outbox_lease_heartbeat(
    stop: asyncio.Event,
    *,
    event_id: uuid.UUID,
    worker_id: str,
    lease_seconds: int,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    interval = max(1.0, lease_seconds / 3)
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
            return
        except TimeoutError:
            pass
        try:
            async with sessions() as session:
                renewed = await outbox.renew_lease(
                    session,
                    event_id,
                    worker_id=worker_id,
                    lease_seconds=lease_seconds,
                )
                if not renewed:
                    await session.rollback()
                    return
                await session.commit()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("outbox lease 续租失败 event=%s", event_id, exc_info=True)


async def process_one(
    session: AsyncSession,
    *,
    worker_id: str,
    event_lease_seconds: int,
    retry_delay_seconds: int,
    sessions: async_sessionmaker[AsyncSession],
    handle_event: EventHandler,
    handle_terminal_failure: TerminalFailureHandler,
) -> bool:
    event = await outbox.claim_next(
        session,
        worker_id=worker_id,
        lease_seconds=event_lease_seconds,
    )
    if event is None:
        await session.rollback()
        return False
    event_id = event.id
    await session.commit()
    heartbeat_stop = asyncio.Event()
    heartbeat = asyncio.create_task(
        outbox_lease_heartbeat(
            heartbeat_stop,
            event_id=event_id,
            worker_id=worker_id,
            lease_seconds=event_lease_seconds,
            sessions=sessions,
        ),
        name=f"outbox-heartbeat-{event_id}",
    )
    try:
        disposition = await handle_event(session, event, worker_id)
        current = await session.get(OutboxEvent, event_id)
        if current is None:
            raise RuntimeError("outbox 事件丢失")
        if disposition.kind == "defer":
            if disposition.retry_at is None:
                raise RuntimeError("deferred outbox event has no retry time")
            await outbox.defer(
                session,
                current,
                worker_id=worker_id,
                available_at=disposition.retry_at,
                reason=disposition.reason,
            )
        else:
            await outbox.complete(session, current, worker_id=worker_id)
        await session.commit()
    except Exception as exc:
        await session.rollback()
        current = await session.get(OutboxEvent, event_id)
        if current is not None:
            terminal = current.attempts >= current.max_attempts
            await outbox.fail(
                session,
                current,
                worker_id=worker_id,
                error=str(exc),
                retry_delay_seconds=retry_delay_seconds,
            )
            if terminal:
                await handle_terminal_failure(session, current, str(exc))
            await session.commit()
        raise
    finally:
        heartbeat_stop.set()
        await asyncio.gather(heartbeat, return_exceptions=True)
    return True
