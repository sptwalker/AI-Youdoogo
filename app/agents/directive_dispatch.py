"""Shared execution skeleton for legacy text-protocol directives."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.contracts import (
    AgentRunner,
    ExecutionContext,
    SkillExecutor,
    SkillRequest,
    SkillResult,
)
from app.models.agent import AgentRole

ExecutorFactory = Callable[[], SkillExecutor]
FailureNote = Callable[[SkillRequest], str]


def merge_execution_context(
    context: ExecutionContext | None,
    *,
    user_id: uuid.UUID | None = None,
    user_intent: str | None = None,
    agent_runner: AgentRunner | None = None,
    exclude: set[str] | None = None,
) -> ExecutionContext:
    """Merge compatibility arguments into one immutable execution context."""
    active = context or ExecutionContext(
        user_id=user_id,
        user_intent=user_intent,
        agent_runner=agent_runner,
    )
    updates: dict[str, Any] = {}
    if active.user_id is None and user_id is not None:
        updates["user_id"] = user_id
    if active.user_intent is None and user_intent is not None:
        updates["user_intent"] = user_intent
    if agent_runner is not None:
        updates["agent_runner"] = agent_runner
    requested_exclusions = frozenset(exclude or ())
    if requested_exclusions:
        updates["excluded_skills"] = active.excluded_skills | requested_exclusions
    return active.model_copy(update=updates) if updates else active


async def dispatch_requests(
    db: AsyncSession,
    role: AgentRole,
    requests: Iterable[SkillRequest],
    context: ExecutionContext,
    *,
    executor_factory: ExecutorFactory,
    failure_note: FailureNote,
) -> SkillResult:
    """Dispatch independent legacy directives while isolating each failure."""
    merged = SkillResult()
    for request in requests:
        try:
            if context.dispatcher is not None:
                part = await context.dispatcher.dispatch(db, role, request, context)
            else:
                part = await executor_factory().execute(db, role, request, context)
            merged.merge(part)
        except Exception:  # noqa: BLE001 - one legacy directive must not abort its peers
            merged.notes.append(failure_note(request))
    return merged
