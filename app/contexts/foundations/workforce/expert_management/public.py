"""Published Expert roster queries for adapters in other Contexts."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.workforce.expert_management.contracts.directory import (
    ExpertDirectoryPort as ExpertDirectoryPort,
)
from app.contexts.foundations.workforce.expert_management.contracts.execution import (
    ExpertExecutionSnapshot,
)
from app.contexts.foundations.workforce.expert_management.contracts.provisioning import (
    ExpertProvisioningPort as ExpertProvisioningPort,
)
from app.contexts.foundations.workforce.expert_management.contracts.roster import (
    DepartmentExpertCount,
    ExpertRosterSnapshot,
)
from app.contexts.foundations.workforce.expert_management.entrypoints import (
    operations as request_operations,
)
from app.contexts.foundations.workforce.expert_management.entrypoints.legacy import (
    LegacyExpertView,
    legacy_view,
)
from app.contexts.foundations.workforce.expert_management.infrastructure.directory_adapter import (
    LocalExpertDirectoryAdapter,
)
from app.contexts.foundations.workforce.expert_management.infrastructure.provisioning_adapter import (  # noqa: E501
    LocalExpertProvisioningAdapter,
)
from app.contexts.foundations.workforce.expert_management.infrastructure.sqlalchemy_query import (
    SQLAlchemyExpertRosterQuery,
    SQLAlchemyExpertSnapshotQuery,
)

# ── 旧位置重复导入清理标记（此处为唯一 import 块）──


async def get_expert_roster(
    session: AsyncSession, expert_id: uuid.UUID
) -> ExpertRosterSnapshot | None:
    """Return one immutable roster snapshot without exposing the query adapter."""
    return await SQLAlchemyExpertRosterQuery(session).get_roster_by_id(expert_id)


async def get_expert_execution(
    session: AsyncSession, expert_id: uuid.UUID
) -> ExpertExecutionSnapshot | None:
    """Return active immutable execution configuration for one expert."""
    return await SQLAlchemyExpertSnapshotQuery(session).get_by_id(expert_id)


async def list_expert_roster(
    session: AsyncSession, *, include_personal: bool = True
) -> tuple[ExpertRosterSnapshot, ...]:
    """Return immutable roster snapshots for published read-only collaboration."""
    return await SQLAlchemyExpertRosterQuery(session).list_roster(include_personal=include_personal)


async def list_department_roster(
    session: AsyncSession, department_id: uuid.UUID
) -> tuple[ExpertRosterSnapshot, ...]:
    return await request_operations.list_department_roster(session, department_id)


async def count_by_department(
    session: AsyncSession, *, include_personal: bool
) -> tuple[DepartmentExpertCount, ...]:
    return await request_operations.count_by_department(
        session,
        include_personal=include_personal,
    )


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
    return await request_operations.create_expert(
        session,
        name=name,
        prompt_template=prompt_template,
        duty=duty,
        model_role=model_role,
        department_id=department_id,
        permission_scope=permission_scope,
        tools=tools,
        tier=tier,
        title=title,
        report_to_id=report_to_id,
        owner_user_id=owner_user_id,
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
    return await request_operations.update_expert(
        session,
        expert_id=expert_id,
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


async def delete_expert(session: AsyncSession, expert_id: uuid.UUID) -> None:
    await request_operations.delete_expert(session, expert_id)


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
    duty: str | None,
    report_to_id: uuid.UUID | None,
) -> ExpertRosterSnapshot:
    return await request_operations.seed_expert(
        session,
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


def build_local_expert_directory_port(session: AsyncSession) -> ExpertDirectoryPort:
    """Phase 1 换 RemoteExpertDirectoryAdapter 的唯一切换点——跨 Context 消费方一律经此拿端口。"""
    return LocalExpertDirectoryAdapter(session)


def build_local_expert_provisioning_port(session: AsyncSession) -> ExpertProvisioningPort:
    """Phase 1 换 RemoteExpertProvisioningAdapter 的唯一切换点——跨 Context 写消费方一律经此落库。"""
    return LocalExpertProvisioningAdapter(session)


def to_legacy_view(snapshot: ExpertRosterSnapshot) -> LegacyExpertView:
    """Adapt a published snapshot for callers retaining the historical attributes."""
    return legacy_view(snapshot)
