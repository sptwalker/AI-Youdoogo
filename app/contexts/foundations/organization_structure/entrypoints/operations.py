"""Request-scoped Organization Structure operations."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.organization_structure.application.contracts import (
    CreateDepartmentCommand,
    SeedOrganizationTemplateCommand,
    SetSupervisorCommand,
    UpdateDepartmentCommand,
)
from app.contexts.foundations.organization_structure.application.use_cases import (
    OrganizationStructureApplication,
)
from app.contexts.foundations.organization_structure.contracts import (
    DepartmentSnapshot,
    OrganizationSnapshot,
)
from app.contexts.foundations.organization_structure.infrastructure.composition import (
    build_organization_structure_application,
)
from app.contexts.foundations.workforce.expert_management import public as expert_public
from app.contexts.foundations.workforce.expert_management.contracts.roster import (
    ExpertRosterSnapshot,
)


def _application(session: AsyncSession) -> OrganizationStructureApplication:
    return build_organization_structure_application(session)


async def get_node(
    session: AsyncSession,
    department_id: uuid.UUID,
) -> DepartmentSnapshot:
    return await _application(session).get_node(department_id)


async def get_snapshot(
    session: AsyncSession,
) -> OrganizationSnapshot:
    return await _application(session).get_snapshot()


async def create_department(
    session: AsyncSession,
    *,
    name: str,
    parent_id: uuid.UUID,
    code: str | None,
) -> DepartmentSnapshot:
    return await _application(session).create_department(
        CreateDepartmentCommand(name=name, parent_id=parent_id, code=code)
    )


async def update_department(
    session: AsyncSession,
    *,
    department_id: uuid.UUID,
    name: str | None,
    sort_order: int | None,
) -> DepartmentSnapshot:
    return await _application(session).update_department(
        UpdateDepartmentCommand(
            department_id=department_id,
            name=name,
            sort_order=sort_order,
        )
    )


async def delete_department(
    session: AsyncSession,
    department_id: uuid.UUID,
) -> None:
    await _application(session).delete_department(department_id)


async def set_supervisor(
    session: AsyncSession,
    *,
    department_id: uuid.UUID,
    supervisor_user_id: uuid.UUID | None,
) -> DepartmentSnapshot:
    return await _application(session).set_supervisor(
        SetSupervisorCommand(
            department_id=department_id,
            supervisor_user_id=supervisor_user_id,
        )
    )


async def list_department_employees(
    session: AsyncSession,
    department_id: uuid.UUID,
) -> tuple[ExpertRosterSnapshot, ...]:
    return await _application(session).list_department_employees(department_id)


async def ancestor_department_ids(
    session: AsyncSession, department_id: uuid.UUID | None
) -> tuple[uuid.UUID, ...]:
    return await _application(session).ancestor_ids(department_id)


async def create_department_expert(
    session: AsyncSession,
    *,
    department_id: uuid.UUID,
    name: str,
    prompt_template: str,
    duty: str | None,
    model_role: str,
    tier: str,
    title: str,
    report_to_id: uuid.UUID | None,
) -> ExpertRosterSnapshot:
    await _application(session).get_node(department_id)
    return await expert_public.build_local_expert_provisioning_port(session).create(
        name=name,
        prompt_template=prompt_template,
        duty=duty,
        model_role=model_role,
        department_id=department_id,
        permission_scope={},
        tools=[],
        tier=tier,
        title=title,
        report_to_id=report_to_id,
    )


async def update_department_expert(
    session: AsyncSession,
    *,
    expert_id: uuid.UUID,
    name: str | None,
    prompt_template: str | None,
    duty: str | None,
    model_role: str | None,
    is_active: bool | None,
    title: str | None,
    tier: str | None,
    report_to_id: uuid.UUID | None,
    department_id: uuid.UUID | None,
) -> ExpertRosterSnapshot:
    return await expert_public.build_local_expert_provisioning_port(session).update(
        expert_id=expert_id,
        name=name,
        prompt_template=prompt_template,
        duty=duty,
        model_role=model_role,
        is_active=is_active,
        permission_scope=None,
        tools=None,
        title=title,
        tier=tier,
        report_to_id=report_to_id,
        department_id=department_id,
    )


async def delete_department_expert(session: AsyncSession, expert_id: uuid.UUID) -> None:
    await expert_public.build_local_expert_provisioning_port(session).delete(expert_id)


async def seed_org_template(
    session: AsyncSession, *, ceo_user_id: uuid.UUID | None = None
) -> dict[str, object]:
    result = await _application(session).seed_template(
        SeedOrganizationTemplateCommand(ceo_user_id=ceo_user_id)
    )
    return result.as_dict()


async def sync_from_feishu(session: AsyncSession) -> dict[str, int]:
    result = await _application(session).sync_external_directory()
    return result.as_dict()
