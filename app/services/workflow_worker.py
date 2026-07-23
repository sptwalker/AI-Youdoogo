"""Compatibility facade for the Bootstrap-owned workflow worker."""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import run_agent
from app.agents.contracts import AgentRunner
from app.bootstrap import workflow_worker as bootstrap_worker
from app.models.workflow import OutboxEvent
from app.services import discussion_service


async def handle_event(
    db: AsyncSession,
    event: OutboxEvent,
    *,
    worker_id: str,
    agent_runner: AgentRunner | None = None,
) -> Any:
    """Preserve the replaceable legacy Agent runner seam."""
    return await bootstrap_worker.handle_event(
        db,
        event,
        worker_id=worker_id,
        agent_runner=agent_runner or run_agent,
        archive_channel=discussion_service.archive_disbanded_channel,
    )


async def process_one(
    db: AsyncSession,
    *,
    worker_id: str,
    agent_runner: AgentRunner | None = None,
) -> bool:
    """Preserve the legacy session-shaped worker entrypoint."""
    return await bootstrap_worker.process_one(
        db,
        worker_id=worker_id,
        agent_runner=agent_runner or run_agent,
        archive_channel=discussion_service.archive_disbanded_channel,
    )


async def run_once(
    *,
    worker_id: str | None = None,
    agent_runner: AgentRunner | None = None,
) -> bool:
    return await bootstrap_worker.run_once(
        worker_id=worker_id,
        agent_runner=agent_runner or run_agent,
    )


async def run_forever(
    stop: asyncio.Event,
    *,
    worker_id: str,
    agent_runner: AgentRunner | None = None,
) -> None:
    await bootstrap_worker.run_forever(
        stop,
        worker_id=worker_id,
        agent_runner=agent_runner or run_agent,
    )


def start_background_worker() -> asyncio.Task[None] | None:
    return bootstrap_worker.start_background_worker(agent_runner=run_agent)


outbox_lease_heartbeat = bootstrap_worker.outbox_lease_heartbeat
recover_once = bootstrap_worker.recover_once
stop_background_worker = bootstrap_worker.stop_background_worker

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
