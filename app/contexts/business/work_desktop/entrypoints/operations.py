"""Transport-neutral Work Desktop operations."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.business.work_desktop.application.contracts import (
    DeliverableDownloadResult,
    DesktopPrincipal,
)
from app.contexts.business.work_desktop.infrastructure.composition import (
    build_work_desktop_application,
)


async def get_desktop(session: AsyncSession, principal: DesktopPrincipal) -> dict[str, Any]:
    return (await build_work_desktop_application(session).desktop(principal)).as_dict()


async def get_supervised_desktop(
    session: AsyncSession,
    operator: DesktopPrincipal,
    target_user_id: uuid.UUID,
) -> dict[str, Any]:
    result = await build_work_desktop_application(session).supervised_desktop(
        operator,
        target_user_id,
    )
    return result.as_dict()


async def list_deliverables(
    session: AsyncSession,
    principal: DesktopPrincipal,
    *,
    requested_owner_id: uuid.UUID | None = None,
) -> list[dict[str, str | int]]:
    rows = await build_work_desktop_application(session).list_deliverables(
        principal,
        requested_owner_id=requested_owner_id,
    )
    return [row.as_dict() for row in rows]


async def download_deliverable(
    session: AsyncSession,
    principal: DesktopPrincipal,
    deliverable_id: uuid.UUID,
) -> DeliverableDownloadResult:
    return await build_work_desktop_application(session).download_deliverable(
        principal,
        deliverable_id,
    )
