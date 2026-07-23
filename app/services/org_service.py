"""Compatibility facade for Organization Structure."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.organization_structure.entrypoints import operations
from app.contexts.foundations.organization_structure.entrypoints.legacy import (
    LegacyDepartmentView,
    department_view,
    tree_view,
)
from app.contexts.foundations.workforce.expert_management.entrypoints.legacy import (
    LegacyExpertView,
)
from app.contexts.foundations.workforce.expert_management.entrypoints.legacy import (
    legacy_view as expert_legacy_view,
)


async def get_node(db: AsyncSession, dept_id: uuid.UUID) -> LegacyDepartmentView:
    snapshot = await operations.get_node(db, dept_id)
    return department_view(snapshot)


async def get_tree(db: AsyncSession) -> list[dict[str, Any]]:
    return tree_view(await operations.get_snapshot(db))


async def create_node(
    db: AsyncSession,
    *,
    name: str,
    parent_id: uuid.UUID,
    code: str | None = None,
) -> LegacyDepartmentView:
    snapshot = await operations.create_department(
        db,
        name=name,
        parent_id=parent_id,
        code=code,
    )
    return department_view(snapshot)


async def update_node(
    db: AsyncSession,
    dept_id: uuid.UUID,
    *,
    name: str | None = None,
    sort_order: int | None = None,
) -> LegacyDepartmentView:
    snapshot = await operations.update_department(
        db,
        department_id=dept_id,
        name=name,
        sort_order=sort_order,
    )
    return department_view(snapshot)


async def delete_node(db: AsyncSession, dept_id: uuid.UUID) -> None:
    await operations.delete_department(db, dept_id)


async def set_supervisor(
    db: AsyncSession,
    dept_id: uuid.UUID,
    supervisor_user_id: uuid.UUID | None,
) -> LegacyDepartmentView:
    snapshot = await operations.set_supervisor(
        db,
        department_id=dept_id,
        supervisor_user_id=supervisor_user_id,
    )
    return department_view(snapshot)


async def list_employees(db: AsyncSession, dept_id: uuid.UUID) -> list[LegacyExpertView]:
    snapshots = await operations.list_department_employees(db, dept_id)
    return [expert_legacy_view(item) for item in snapshots]
