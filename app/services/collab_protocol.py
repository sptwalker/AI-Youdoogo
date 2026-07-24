"""Compatibility facade for the Collaboration Requests Agent capability."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.contracts import AgentRunner, ExecutionContext, SkillResult
from app.contexts.business.collaboration_requests.application.contracts import (
    CollaborationRequestResult,
)
from app.contexts.business.collaboration_requests.entrypoints import agent_capability
from app.contexts.business.collaboration_requests.entrypoints.agent_capability import (
    PROMPT_SECTION,
    CollabArgs,
    ConsultArgs,
    ParsedDirectives,
    ProtocolResult,
    fold_notes,
    parse,
)
from app.models.agent import AgentRole
from app.services import collab_service, config_service, data_query_service

# Legacy monkeypatch seam. Production paths normally provide ExecutionContext.agent_runner.
run_agent: AgentRunner | None = None


async def _create_request(
    db: AsyncSession,
    **kwargs: Any,
) -> CollaborationRequestResult:
    """Resolve the legacy request seam at call time so monkeypatching remains effective."""
    return await collab_service.create_request(db, **kwargs)


async def _legacy_delivery_fallback(
    db: AsyncSession,
    target: AgentRole,
    output: str,
    context: ExecutionContext,
    _excluded: set[str],
) -> SkillResult:
    from app.contexts.foundations.execution.deliverable_management.entrypoints import (
        agent_capability as delivery_capability,
    )

    return await delivery_capability.execute(
        db,
        target,
        output,
        user_id=context.user_id,
        execution_context=context,
        feature_flag_resolver=config_service.resolve,
    )


async def _legacy_fallback(
    db: AsyncSession,
    target: AgentRole,
    reply_text: str,
    context: ExecutionContext,
    question: str,
) -> SkillResult:
    from app.contexts.foundations.execution.deliverable_management.entrypoints import (
        agent_capability as delivery_capability,
    )
    from app.contexts.foundations.integration.governed_data_query.entrypoints import (
        agent_capability as query_capability,
    )

    excluded = set(context.excluded_skills) | {"collab"}
    result = await query_capability.execute(
        db,
        target,
        reply_text,
        user_id=context.user_id,
        user_intent=question,
        exclude=excluded,
        execution_context=context,
        agent_runner=context.agent_runner,
        feature_flag_resolver=config_service.resolve,
        executor_factory=lambda: query_capability.DataQuerySkillExecutor(
            query_provider=lambda: data_query_service.run_readonly_sql,
            fallback_executor=_legacy_delivery_fallback,
        ),
    )
    result.merge(
        await delivery_capability.execute(
            db,
            target,
            reply_text,
            user_id=context.user_id,
            execution_context=context,
            feature_flag_resolver=config_service.resolve,
        )
    )
    return result


class CollabSkillExecutor(agent_capability.CollabSkillExecutor):
    """Legacy constructor with dynamically resolved compatibility collaborators."""

    def __init__(self) -> None:
        super().__init__(
            runner_provider=lambda: run_agent,
            request_creator=_create_request,
            fallback_executor=_legacy_fallback,
        )


def _executor() -> CollabSkillExecutor:
    return CollabSkillExecutor()


async def execute(
    db: AsyncSession,
    initiator: AgentRole,
    output: str,
    *,
    user_id: uuid.UUID | None = None,
    execution_context: ExecutionContext | None = None,
) -> SkillResult:
    """Preserve the old dynamic seams while delegating behavior to the Context."""
    return await agent_capability.execute(
        db,
        initiator,
        output,
        user_id=user_id,
        execution_context=execution_context,
        runner_provider=lambda: run_agent,
        feature_flag_resolver=config_service.resolve,
        executor_factory=_executor,
    )


__all__ = [
    "CollabArgs",
    "CollabSkillExecutor",
    "ConsultArgs",
    "PROMPT_SECTION",
    "ParsedDirectives",
    "ProtocolResult",
    "collab_service",
    "config_service",
    "data_query_service",
    "execute",
    "fold_notes",
    "parse",
    "run_agent",
]
