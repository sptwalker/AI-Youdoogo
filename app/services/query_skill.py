"""Compatibility facade for the Governed Data Query Agent capability."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.contracts import AgentRunner, ExecutionContext, SkillResult
from app.contexts.foundations.integration.governed_data_query.entrypoints import (
    agent_capability,
)
from app.models.agent import AgentRole
from app.services import config_service, data_query_service

ProtocolResult = SkillResult
DataQueryArgs = agent_capability.DataQueryArgs
parse = agent_capability.parse
prompt_section = agent_capability.prompt_section
_table = agent_capability.render_table

# Historical injection point retained for direct callers and tests.
run_agent: AgentRunner | None = None


async def _legacy_fallback(
    db: AsyncSession,
    initiator: AgentRole,
    output: str,
    context: ExecutionContext,
    _exclude: set[str],
) -> SkillResult:
    from app.contexts.foundations.execution.deliverable_management.entrypoints import (
        agent_capability as delivery_capability,
    )

    return await delivery_capability.execute(
        db,
        initiator,
        output,
        user_id=context.user_id,
        execution_context=context,
        feature_flag_resolver=config_service.resolve,
    )


class DataQuerySkillExecutor(agent_capability.DataQuerySkillExecutor):
    """Compatibility executor preserving the historical mutable runner seam."""

    def __init__(self) -> None:
        super().__init__(
            runner_provider=lambda: run_agent,
            query_provider=lambda: data_query_service.run_readonly_sql,
            fallback_executor=_legacy_fallback,
        )


async def execute(
    db: AsyncSession,
    initiator: AgentRole,
    output: str,
    *,
    user_id: uuid.UUID | None = None,
    user_intent: str | None = None,
    exclude: set[str] | None = None,
    execution_context: ExecutionContext | None = None,
) -> SkillResult:
    return await agent_capability.execute(
        db,
        initiator,
        output,
        user_id=user_id,
        user_intent=user_intent,
        exclude=exclude,
        execution_context=execution_context,
        agent_runner=run_agent,
        feature_flag_resolver=config_service.resolve,
        executor_factory=DataQuerySkillExecutor,
    )


__all__ = [
    "DataQueryArgs",
    "DataQuerySkillExecutor",
    "ProtocolResult",
    "config_service",
    "data_query_service",
    "execute",
    "parse",
    "prompt_section",
    "run_agent",
]
