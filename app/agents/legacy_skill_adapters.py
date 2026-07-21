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

from app.agents.contracts import ExecutionContext, SkillResult
from app.models.agent import AgentRole

LegacyExecutor = Callable[
    [AsyncSession, AgentRole, str, ExecutionContext, set[str]],
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
    role: AgentRole,
    output: str,
    context: ExecutionContext,
    _exclude: set[str],
) -> SkillResult:
    from app.services import collab_protocol

    kwargs = accepted_kwargs(
        collab_protocol.execute,
        {"user_id": context.user_id, "execution_context": context},
    )
    return await collab_protocol.execute(db, role, output, **kwargs)


async def legacy_deliver(
    db: AsyncSession,
    role: AgentRole,
    output: str,
    context: ExecutionContext,
    _exclude: set[str],
) -> SkillResult:
    from app.services import deliver_service

    kwargs = accepted_kwargs(
        deliver_service.execute,
        {"user_id": context.user_id, "execution_context": context},
    )
    return await deliver_service.execute(db, role, output, **kwargs)


async def legacy_query(
    db: AsyncSession,
    role: AgentRole,
    output: str,
    context: ExecutionContext,
    exclude: set[str],
) -> SkillResult:
    from app.services import query_skill

    kwargs = accepted_kwargs(
        query_skill.execute,
        {
            "user_id": context.user_id,
            "user_intent": context.user_intent,
            "exclude": exclude,
            "execution_context": context,
        },
    )
    return await query_skill.execute(db, role, output, **kwargs)
