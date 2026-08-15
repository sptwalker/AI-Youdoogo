"""Transport-neutral Work Desktop operations."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.business.work_desktop.application.contracts import (
    DeliverableDownloadResult,
    DesktopPrincipal,
    InboxItemRef,
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


async def mark_inbox(
    session: AsyncSession,
    principal: DesktopPrincipal,
    items: tuple[InboxItemRef, ...],
    *,
    is_read: bool | None = None,
    is_processed: bool | None = None,
) -> dict[str, int]:
    """批量置读/处理态（真人确认触发）。仅写本人读态，改后提交。"""
    count = await build_work_desktop_application(session).mark_inbox(
        principal, items, is_read=is_read, is_processed=is_processed
    )
    await session.commit()
    return {"marked": count}


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
