"""Request-scoped Expert Management operations."""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.workforce.expert_management.application.contracts import (
    CreateExpertCommand,
    SeedExpertCommand,
    UpdateExpertCommand,
)
from app.contexts.foundations.workforce.expert_management.contracts.roster import (
    DepartmentExpertCount,
    ExpertRosterSnapshot,
)
from app.contexts.foundations.workforce.expert_management.infrastructure.composition import (
    build_expert_management_application,
)


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


async def create_expert(
    session: AsyncSession,
    *,
    name: str,
    prompt_template: str,
    duty: str | None,
    model_role: str,
    department_id: uuid.UUID | None,
    permission_scope: dict[str, Any],
    tools: list[Any],
    tier: str,
    title: str,
    report_to_id: uuid.UUID | None,
    owner_user_id: uuid.UUID | None = None,
) -> ExpertRosterSnapshot:
    return await build_expert_management_application(session).create(
        CreateExpertCommand(
            name=name,
            prompt_template=prompt_template,
            duty=duty,
            model_role=model_role,
            department_id=department_id,
            permission_scope_json=_json(permission_scope),
            tools_json=_json(tools),
            tier=tier,
            title=title,
            report_to_id=report_to_id,
            owner_user_id=owner_user_id,
        )
    )


async def update_expert(
    session: AsyncSession,
    *,
    expert_id: uuid.UUID,
    name: str | None,
    prompt_template: str | None,
    duty: str | None,
    model_role: str | None,
    is_active: bool | None,
    permission_scope: dict[str, Any] | None,
    tools: list[Any] | None,
    title: str | None,
    tier: str | None,
    report_to_id: uuid.UUID | None,
    department_id: uuid.UUID | None,
) -> ExpertRosterSnapshot:
    return await build_expert_management_application(session).update(
        UpdateExpertCommand(
            expert_id=expert_id,
            name=name,
            prompt_template=prompt_template,
            duty=duty,
            model_role=model_role,
            is_active=is_active,
            permission_scope_json=_json(permission_scope) if permission_scope is not None else None,
            tools_json=_json(tools) if tools is not None else None,
            title=title,
            tier=tier,
            report_to_id=report_to_id,
            department_id=department_id,
        )
    )


async def seed_expert(
    session: AsyncSession,
    *,
    code: str,
    name: str,
    prompt_template: str,
    title: str,
    tier: str,
    model_role: str,
    department_id: uuid.UUID | None,
    duty: str | None = None,
    report_to_id: uuid.UUID | None = None,
) -> ExpertRosterSnapshot:
    return await build_expert_management_application(session).seed(
        SeedExpertCommand(
            code=code,
            name=name,
            prompt_template=prompt_template,
            title=title,
            tier=tier,
            model_role=model_role,
            department_id=department_id,
            duty=duty,
            report_to_id=report_to_id,
        )
    )


async def delete_expert(session: AsyncSession, expert_id: uuid.UUID) -> None:
    await build_expert_management_application(session).delete(expert_id)


async def list_roster(
    session: AsyncSession, *, include_personal: bool = False
) -> tuple[ExpertRosterSnapshot, ...]:
    return await build_expert_management_application(session).list_roster(
        include_personal=include_personal
    )


async def list_department_roster(
    session: AsyncSession, department_id: uuid.UUID
) -> tuple[ExpertRosterSnapshot, ...]:
    return await build_expert_management_application(session).list_department_roster(department_id)


async def count_by_department(
    session: AsyncSession, *, include_personal: bool
) -> tuple[DepartmentExpertCount, ...]:
    return await build_expert_management_application(session).count_by_department(
        include_personal=include_personal
    )
