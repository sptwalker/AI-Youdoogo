"""Outbox event routing for durable workflows."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.contracts import AgentRunner
from app.models.workflow import (
    RUN_CANCELLED,
    RUN_FAILED,
    RUN_SUCCEEDED,
    RUN_WAITING_HUMAN,
    OutboxEvent,
)
from app.services import (
    discussion_service,
    outbox_service,
    workflow_service,
    workflow_step_executor,
)


async def enqueue_ready_steps(db: AsyncSession, workflow_id: uuid.UUID) -> int:
    run = await workflow_service.get_run(db, workflow_id)
    await workflow_service.refresh_run_status(db, run)
    if run.status in (RUN_SUCCEEDED, RUN_FAILED, RUN_CANCELLED, RUN_WAITING_HUMAN):
        return 0
    steps = await workflow_service.list_steps(db, workflow_id)
    ready = workflow_service.ready_steps(steps)
    for step in ready:
        await outbox_service.enqueue(
            db,
            aggregate_type="workflow_step",
            aggregate_id=step.id,
            event_type="workflow.step.execute",
            dedupe_key=f"workflow-step:{step.id}:execute:v{step.version}",
            payload={
                "workflow_run_id": str(workflow_id),
                "workflow_step_id": str(step.id),
                "trace_id": str(run.trace_id),
            },
        )
    return len(ready)


async def handle_event(
    db: AsyncSession,
    event: OutboxEvent,
    *,
    worker_id: str,
    agent_runner: AgentRunner,
) -> workflow_step_executor.StepExecutionDisposition:
    """处理一条已抢占事件并返回 Outbox disposition。"""
    if event.event_type == "workflow.advance":
        workflow_id = uuid.UUID(str(event.payload["workflow_run_id"]))
        await enqueue_ready_steps(db, workflow_id)
        return workflow_step_executor.StepExecutionDisposition.complete()
    if event.event_type == "workflow.step.execute":
        return await workflow_step_executor.execute_step(
            db, event, worker_id=worker_id, agent_runner=agent_runner
        )
    if event.event_type == discussion_service.DISBAND_ARCHIVE_EVENT:
        raw_channel_id = event.payload.get("channel_id") or event.aggregate_id
        await discussion_service.archive_disbanded_channel(
            db, uuid.UUID(str(raw_channel_id))
        )
        return workflow_step_executor.StepExecutionDisposition.complete()
    raise ValueError(f"未知 outbox event_type：{event.event_type}")
