"""Legacy text-protocol adapters for the typed skill runtime.

These adapters translate existing Chinese directives through the current service
entrypoints. They intentionally depend only on typed contracts and injected
execution context, never on the concrete Agent runtime.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.contracts import AgentSubject, ExecutionContext, SkillResult
from app.agents.directive_dispatch import dispatch_requests as dispatch_requests
from app.agents.directive_dispatch import (
    merge_execution_context as merge_execution_context,
)

LegacyExecutor = Callable[
    [AsyncSession, AgentSubject, str, ExecutionContext, set[str]],
    Awaitable[SkillResult],
]


def accepted_kwargs(call: Any, values: dict[str, Any]) -> dict[str, Any]:
    """Pass only compatibility arguments declared by an old plugin or test stub."""
    try:
        params = inspect.signature(call).parameters
    except (TypeError, ValueError):
        return values
    if any(param.kind == inspect.Parameter.VAR_KEYWORD for param in params.values()):
        return values
    return {key: value for key, value in values.items() if key in params}


async def legacy_collab(
    db: AsyncSession,
    role: AgentSubject,
    output: str,
    context: ExecutionContext,
    _exclude: set[str],
) -> SkillResult:
    from app.contexts.business.collaboration_requests.entrypoints import agent_capability

    kwargs = accepted_kwargs(
        agent_capability.execute,
        {
            "user_id": context.user_id,
            "exclude": _exclude,
            "execution_context": context,
        },
    )
    return await agent_capability.execute(db, role, output, **kwargs)


async def legacy_deliver(
    db: AsyncSession,
    role: AgentSubject,
    output: str,
    context: ExecutionContext,
    _exclude: set[str],
) -> SkillResult:
    from app.contexts.foundations.execution.deliverable_management.entrypoints import (
        agent_capability,
    )

    kwargs = accepted_kwargs(
        agent_capability.execute,
        {"user_id": context.user_id, "execution_context": context},
    )
    return await agent_capability.execute(db, role, output, **kwargs)


async def legacy_query(
    db: AsyncSession,
    role: AgentSubject,
    output: str,
    context: ExecutionContext,
    exclude: set[str],
) -> SkillResult:
    from app.contexts.foundations.integration.governed_data_query.entrypoints import (
        agent_capability,
    )

    kwargs = accepted_kwargs(
        agent_capability.execute,
        {
            "user_id": context.user_id,
            "user_intent": context.user_intent,
            "exclude": exclude,
            "execution_context": context,
        },
    )
    return await agent_capability.execute(db, role, output, **kwargs)


async def legacy_read_url(
    db: AsyncSession,
    role: AgentSubject,
    output: str,
    context: ExecutionContext,
    exclude: set[str],
) -> SkillResult:
    from app.contexts.foundations.integration.read_url.entrypoints import (
        agent_capability,
    )

    kwargs = accepted_kwargs(
        agent_capability.execute,
        {
            "user_id": context.user_id,
            "user_intent": context.user_intent,
            "exclude": exclude,
            "execution_context": context,
        },
    )
    return await agent_capability.execute(db, role, output, **kwargs)
