"""One-way compatibility facade for Organization's Feishu directory sync."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.identity import public as identity_public
from app.contexts.foundations.organization_structure.application.contracts import (
    ExternalDepartmentRecord,
)
from app.contexts.foundations.organization_structure.application.use_cases import (
    sort_external_departments,
)
from app.contexts.foundations.organization_structure.entrypoints import operations


def _sort_by_hierarchy(departments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compatibility translation for callers of the former pure helper."""
    by_external_id = {
        str(item["open_department_id"]): item
        for item in departments
        if item.get("open_department_id")
    }
    records = tuple(
        ExternalDepartmentRecord(
            external_id=external_id,
            parent_external_id=(
                str(item["parent_department_id"])
                if item.get("parent_department_id")
                else None
            ),
            name=str(item.get("name") or "未命名部门"),
        )
        for external_id, item in by_external_id.items()
    )
    return [by_external_id[item.external_id] for item in sort_external_departments(records)]


async def sync_from_feishu(db: AsyncSession) -> dict[str, int]:
    return await operations.sync_from_feishu(db)


async def list_feishu_users(db: AsyncSession, *, limit: int = 500) -> list[dict[str, Any]]:
    """Compatibility read retained until its independent Identity route migrates."""
    users = sorted(
        (
            user
            for user in await identity_public.list_users(db)
            if user.feishu_open_id is not None and not user.is_delete
        ),
        key=lambda user: user.real_name,
    )[:limit]
    return [
        {
            "id": str(user.id),
            "real_name": user.real_name,
            "en_name": user.en_name,
            "title": user.title,
            "department_id": str(user.department_id) if user.department_id else None,
            "avatar_url": user.avatar_url,
        }
        for user in users
    ]
