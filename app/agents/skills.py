"""Compatibility facade for the modular typed skill runtime."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.contracts import ExecutionContext, SkillResult
from app.agents.skill_registry import REGISTRY, Skill, enabled_skills, prompt_sections
from app.agents.tool_dispatcher import ToolDispatcher
from app.models.agent import AgentRole
from app.services import config_service as config_service

__all__ = [
    "REGISTRY",
    "Skill",
    "ToolDispatcher",
    "enabled_skills",
    "execute_all",
    "fold_notes",
    "prompt_sections",
]


async def execute_all(
    db: AsyncSession,
    role: AgentRole,
    output: str,
    *,
    user_id: UUID | None = None,
    user_intent: str | None = None,
    exclude: set[str] | None = None,
    execution_context: ExecutionContext | None = None,
) -> SkillResult:
    """Preserve the legacy text entrypoint while carrying durable context."""
    context = execution_context or ExecutionContext(
        user_id=user_id,
        user_intent=user_intent,
    )
    updates: dict[str, Any] = {}
    if context.user_id is None and user_id is not None:
        updates["user_id"] = user_id
    if context.user_intent is None and user_intent is not None:
        updates["user_intent"] = user_intent
    if updates:
        context = context.model_copy(update=updates)
    return await ToolDispatcher().dispatch_text(db, role, output, context, exclude=exclude)


def fold_notes(text: str, result: SkillResult) -> str:
    """Fold runtime notes into the visible response body."""
    if not result.notes:
        return text
    return text + "\n\n" + "\n".join(f"> 系统：{note}" for note in result.notes)
