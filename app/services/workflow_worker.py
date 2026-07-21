"""Durable workflow worker lifecycle facade."""

from __future__ import annotations

import asyncio
import logging
import socket
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import run_agent
from app.agents.contracts import AgentRunner
from app.core.config import get_settings
from app.core.database import async_session_factory
from app.models.workflow import OutboxEvent
from app.services import outbox_service, workflow_event_handler, workflow_recovery, workflow_service

logger = logging.getLogger(__name__)

_worker_task: asyncio.Task[None] | None = None
_stop_event: asyncio.Event | None = None


def _worker_id() -> str:
    return f"{socket.gethostname()}:{uuid.uuid4().hex[:12]}"


async def handle_event(
    db: AsyncSession,
    event: OutboxEvent,
    *,
    worker_id: str,
    agent_runner: AgentRunner | None = None,
) -> Any:
    """兼容入口；默认使用当前 Agent runtime。"""
    return await workflow_event_handler.handle_event(
        db,
        event,
        worker_id=worker_id,
        agent_runner=agent_runner or run_agent,
    )


async def process_one(
    db: AsyncSession,
    *,
    worker_id: str,
    agent_runner: AgentRunner | None = None,
) -> bool:
    """抢占并处理一条事件；供后台循环和单测复用。"""
    settings = get_settings()
    event = await outbox_service.claim_next(
        db,
        worker_id=worker_id,
        lease_seconds=settings.workflow_event_lease_seconds,
    )
    if event is None:
        await db.rollback()
        return False
    await db.commit()
    try:
        disposition = await handle_event(
            db, event, worker_id=worker_id, agent_runner=agent_runner
        )
        current = await db.get(OutboxEvent, event.id)
        if current is None:
            raise RuntimeError("outbox 事件丢失")
        if disposition.kind == "defer":
            await outbox_service.defer(
                db,
                current,
                worker_id=worker_id,
                available_at=disposition.retry_at,
                reason=disposition.reason,
            )
        else:
            await outbox_service.complete(db, current, worker_id=worker_id)
        await db.commit()
    except Exception as exc:
        await db.rollback()
        current = await db.get(OutboxEvent, event.id)
        if current is not None:
            terminal = current.attempts >= current.max_attempts
            await outbox_service.fail(
                db,
                current,
                worker_id=worker_id,
                error=str(exc),
                retry_delay_seconds=settings.workflow_retry_delay_seconds,
            )
            if terminal:
                await workflow_service.fail_from_outbox(db, current, error=str(exc))
            await db.commit()
        raise
    return True


async def recover_once() -> int:
    """使用独立会话补发过期步骤；失败不影响普通事件循环。"""
    settings = get_settings()
    async with async_session_factory() as db:
        count = await workflow_recovery.requeue_expired_steps(
            db, batch_size=settings.workflow_recovery_batch_size
        )
        await db.commit()
        return count


async def run_once(*, worker_id: str | None = None) -> bool:
    """使用独立会话处理一条事件。"""
    async with async_session_factory() as db:
        return await process_one(db, worker_id=worker_id or _worker_id())


async def run_forever(stop: asyncio.Event, *, worker_id: str) -> None:
    """后台轮询循环；单次故障隔离，不阻断应用。"""
    settings = get_settings()
    poll = max(0.1, settings.workflow_worker_poll_seconds)
    recovery_after = 0.0
    loop = asyncio.get_running_loop()
    while not stop.is_set():
        worked = False
        now = loop.time()
        if now >= recovery_after:
            try:
                await recover_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("workflow step recovery scan failed", exc_info=True)
            recovery_after = now + max(1.0, settings.workflow_recovery_scan_seconds)
        try:
            worked = await run_once(worker_id=worker_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("workflow worker 处理失败", exc_info=True)
        if worked:
            continue
        try:
            await asyncio.wait_for(stop.wait(), timeout=poll)
        except TimeoutError:
            pass


def start_background_worker() -> asyncio.Task[None] | None:
    """启动应用内 worker；多 Web 进程由租约保证安全。"""
    global _stop_event, _worker_task
    if not get_settings().workflow_worker_enabled:
        return None
    if _worker_task is not None and not _worker_task.done():
        return _worker_task
    _stop_event = asyncio.Event()
    _worker_task = asyncio.create_task(
        run_forever(_stop_event, worker_id=_worker_id()), name="workflow-outbox-worker"
    )
    return _worker_task


async def stop_background_worker() -> None:
    """通知 worker 停止并等待当前循环退出。"""
    global _stop_event, _worker_task
    if _worker_task is None:
        return
    if _stop_event is not None:
        _stop_event.set()
    try:
        await asyncio.wait_for(_worker_task, timeout=5)
    except TimeoutError:
        _worker_task.cancel()
        await asyncio.gather(_worker_task, return_exceptions=True)
    finally:
        _worker_task = None
        _stop_event = None
