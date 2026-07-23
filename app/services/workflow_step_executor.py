"""One-way compatibility facade for Workflow step execution."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.contracts import AgentRunner
from app.contexts.business.task_management.infrastructure.sqlalchemy_adapter import (
    SQLAlchemyTaskManagementAdapter,
)
from app.contexts.foundations.execution.workflow_runtime.infrastructure import (
    legacy_execution,
)
from app.contexts.foundations.workforce.expert_management.infrastructure.sqlalchemy_query import (
    SQLAlchemyExpertSnapshotQuery,
)
from app.models.workflow import OutboxEvent

StepExecutionDisposition = legacy_execution.StepExecutionDisposition
lease_heartbeat = legacy_execution.lease_heartbeat
step_message = legacy_execution.step_message


async def execute_step(
    db: AsyncSession,
    event: OutboxEvent,
    *,
    worker_id: str,
    agent_runner: AgentRunner,
) -> StepExecutionDisposition:
    return await legacy_execution.execute_step(
        db,
        event,
        worker_id=worker_id,
        agent_runner=agent_runner,
        task_projection=SQLAlchemyTaskManagementAdapter(db),
        experts=SQLAlchemyExpertSnapshotQuery(db),
    )


__all__ = [
    "StepExecutionDisposition",
    "execute_step",
    "lease_heartbeat",
    "step_message",
]
