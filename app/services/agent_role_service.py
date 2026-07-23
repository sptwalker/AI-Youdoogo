"""Compatibility facade for Expert Management lifecycle and roster."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.workforce.expert_management.domain.models import (
    VALID_MODEL_ROLES,
    VALID_TIERS,
)
from app.contexts.foundations.workforce.expert_management.entrypoints import operations
from app.contexts.foundations.workforce.expert_management.entrypoints.legacy import legacy_view

if TYPE_CHECKING:
    from app.models.agent import AgentRole


async def create_agent_role(
    db: AsyncSession,
    *,
    name: str,
    prompt_template: str,
    duty: str | None = None,
    model_role: str = "daily",
    department_id: uuid.UUID | None = None,
    permission_scope: dict[str, Any] | None = None,
    tools: list[Any] | None = None,
    tier: str = "member",
    title: str = "",
    report_to_id: uuid.UUID | None = None,
) -> AgentRole:
    snapshot = await operations.create_expert(
        db,
        name=name,
        prompt_template=prompt_template,
        duty=duty,
        model_role=model_role,
        department_id=department_id,
        permission_scope=permission_scope or {},
        tools=tools or [],
        tier=tier,
        title=title,
        report_to_id=report_to_id,
    )
    return cast("AgentRole", legacy_view(snapshot))


async def update_agent_role(
    db: AsyncSession,
    role_id: uuid.UUID,
    *,
    name: str | None = None,
    prompt_template: str | None = None,
    duty: str | None = None,
    model_role: str | None = None,
    is_active: bool | None = None,
    permission_scope: dict[str, Any] | None = None,
    tools: list[Any] | None = None,
    title: str | None = None,
    tier: str | None = None,
    report_to_id: uuid.UUID | None = None,
    department_id: uuid.UUID | None = None,
) -> AgentRole:
    snapshot = await operations.update_expert(
        db,
        expert_id=role_id,
        name=name,
        prompt_template=prompt_template,
        duty=duty,
        model_role=model_role,
        is_active=is_active,
        permission_scope=permission_scope,
        tools=tools,
        title=title,
        tier=tier,
        report_to_id=report_to_id,
        department_id=department_id,
    )
    return cast("AgentRole", legacy_view(snapshot))


async def delete_agent_role(db: AsyncSession, role_id: uuid.UUID) -> None:
    await operations.delete_expert(db, role_id)


async def list_agent_roles(db: AsyncSession) -> list[AgentRole]:
    snapshots = await operations.list_roster(db)
    return cast("list[AgentRole]", [legacy_view(snapshot) for snapshot in snapshots])


__all__ = [
    "VALID_MODEL_ROLES",
    "VALID_TIERS",
    "create_agent_role",
    "delete_agent_role",
    "list_agent_roles",
    "update_agent_role",
]
