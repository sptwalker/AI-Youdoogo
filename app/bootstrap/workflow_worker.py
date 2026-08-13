"""Compose and manage the durable workflow outbox worker."""

from __future__ import annotations

import asyncio
import logging
import socket
import uuid
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.contracts import AgentRunner
from app.bootstrap import workflow_events
from app.contexts.business.task_management.infrastructure.sqlalchemy_adapter import (
    SQLAlchemyTaskManagementAdapter,
)
from app.contexts.foundations.execution.agent_execution.public import (
    run_agent_snapshot,
)
from app.contexts.foundations.execution.workflow_runtime.infrastructure import (
    failure_propagation,
)
from app.contexts.foundations.execution.workflow_runtime.infrastructure import (
    worker as worker_runtime,
)
from app.contexts.foundations.execution.workflow_runtime.infrastructure.sqlalchemy_recovery import (
    requeue_expired_steps,
)
from app.core.config import get_settings
from app.models.workflow import OutboxEvent
from app.platform.database import async_session_factory

logger = logging.getLogger(__name__)

_worker_task: asyncio.Task[None] | None = None
_stop_event: asyncio.Event | None = None

# Compatibility name retained for existing worker injection/monkeypatch seams.  It now
# points at the pure snapshot runner rather than the ORM-shaped legacy entrypoint.
run_agent = cast(AgentRunner, run_agent_snapshot)


def _worker_id() -> str:
    return f"{socket.gethostname()}:{uuid.uuid4().hex[:12]}"


async def handle_event(
    session: AsyncSession,
    event: OutboxEvent,
    *,
    worker_id: str,
    agent_runner: AgentRunner | None = None,
    archive_channel: workflow_events.ArchiveChannel | None = None,
) -> Any:
    """Handle one event with the configured Agent runtime."""
    return await workflow_events.handle_event(
        session,
        event,
        worker_id=worker_id,
        agent_runner=agent_runner or run_agent,
        archive_channel=archive_channel,
    )


async def outbox_lease_heartbeat(
    stop: asyncio.Event,
    *,
    event_id: uuid.UUID,
    worker_id: str,
    lease_seconds: int,
) -> None:
    await worker_runtime.outbox_lease_heartbeat(
        stop,
        event_id=event_id,
        worker_id=worker_id,
        lease_seconds=lease_seconds,
        sessions=async_session_factory,
    )


async def _handle_terminal_failure(
    session: AsyncSession,
    event: OutboxEvent,
    error: str,
) -> None:
    if event.aggregate_type in {"workflow", "workflow_step"}:
        await failure_propagation.fail_from_outbox(
            session,
            event,
            error=error,
            task_projection=SQLAlchemyTaskManagementAdapter(session),
        )
        return
    logger.error(
        "非 workflow outbox 重试耗尽 event=%s type=%s error=%s",
        event.id,
        event.event_type,
        error,
    )


async def process_one(
    session: AsyncSession,
    *,
    worker_id: str,
    agent_runner: AgentRunner | None = None,
    archive_channel: workflow_events.ArchiveChannel | None = None,
) -> bool:
    """Claim and process one event with the runtime's lease policy."""
    settings = get_settings()

    async def _handle(
        active_session: AsyncSession,
        event: OutboxEvent,
        owner: str,
    ) -> Any:
        return await handle_event(
            active_session,
            event,
            worker_id=owner,
            agent_runner=agent_runner,
            archive_channel=archive_channel,
        )

    return await worker_runtime.process_one(
        session,
        worker_id=worker_id,
        event_lease_seconds=settings.workflow_event_lease_seconds,
        retry_delay_seconds=settings.workflow_retry_delay_seconds,
        sessions=async_session_factory,
        handle_event=_handle,
        handle_terminal_failure=_handle_terminal_failure,
    )


async def recover_once() -> int:
    """Requeue expired steps in a separate transaction."""
    settings = get_settings()
    async with async_session_factory() as session:
        count = await requeue_expired_steps(
            session,
            batch_size=settings.workflow_recovery_batch_size,
        )
        await session.commit()
        return count


async def run_once(
    *,
    worker_id: str | None = None,
    agent_runner: AgentRunner | None = None,
) -> bool:
    """Process one event in a separate session."""
    async with async_session_factory() as session:
        return await process_one(
            session,
            worker_id=worker_id or _worker_id(),
            agent_runner=agent_runner,
        )


async def run_forever(
    stop: asyncio.Event,
    *,
    worker_id: str,
    agent_runner: AgentRunner | None = None,
) -> None:
    """Poll until stopped while isolating recovery and event failures."""
    settings = get_settings()
    poll = max(0.1, settings.workflow_worker_poll_seconds)
    recovery_after = 0.0
    schedule_after = 0.0
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
        if settings.report_scheduler_enabled and now >= schedule_after:
            # 复用本时钟闸做定时报告扫描（docs/25 P1-1）；发起走 plan_work → start_workflow
            # 同一红线入口。datetime.now()=服务器本地时，day_of_month/hour 据此判定；
            # ponytail: 多区部署再加 tz 设置、届时传 aware datetime（当前单区中国部署够用）。
            from datetime import datetime

            from app.bootstrap import report_scheduler

            try:
                await report_scheduler.scan_once(datetime.now())
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("定时报告扫描失败", exc_info=True)
            schedule_after = now + max(1.0, settings.report_schedule_scan_seconds)
        try:
            worked = await run_once(worker_id=worker_id, agent_runner=agent_runner)
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


def start_background_worker(
    *,
    agent_runner: AgentRunner | None = None,
) -> asyncio.Task[None] | None:
    """Start the in-process worker when enabled."""
    global _stop_event, _worker_task
    if not get_settings().workflow_worker_enabled:
        return None
    if _worker_task is not None and not _worker_task.done():
        return _worker_task
    _stop_event = asyncio.Event()
    _worker_task = asyncio.create_task(
        run_forever(
            _stop_event,
            worker_id=_worker_id(),
            agent_runner=agent_runner,
        ),
        name="workflow-outbox-worker",
    )
    return _worker_task


async def stop_background_worker() -> None:
    """Request shutdown and wait for the active poll iteration."""
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


__all__ = [
    "handle_event",
    "outbox_lease_heartbeat",
    "process_one",
    "recover_once",
    "run_forever",
    "run_once",
    "start_background_worker",
    "stop_background_worker",
]
