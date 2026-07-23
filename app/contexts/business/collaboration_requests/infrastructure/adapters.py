"""Outer adapters used by Collaboration Requests."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.business.collaboration_requests.application.ports import AuditRequest
from app.models.system import SysDepartment
from app.services import audit_service


class OrganizationReviewScopeAdapter:
    """Translate Organization persistence into a caller-owned review scope."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def reviewable_department_ids(
        self, *, supervisor_user_id: uuid.UUID, is_admin: bool
    ) -> tuple[uuid.UUID, ...] | None:
        if is_admin:
            return None
        rows = (
            await self._session.execute(
                select(SysDepartment.id).where(
                    SysDepartment.supervisor_user_id == supervisor_user_id,
                    SysDepartment.is_delete.is_(False),
                )
            )
        ).scalars()
        return tuple(rows)

    async def can_review(
        self,
        *,
        reviewer_id: uuid.UUID,
        target_department_id: uuid.UUID,
        is_admin: bool,
    ) -> bool:
        if is_admin:
            return True
        supervisor_id = (
            await self._session.execute(
                select(SysDepartment.supervisor_user_id).where(
                    SysDepartment.id == target_department_id,
                    SysDepartment.is_delete.is_(False),
                )
            )
        ).scalar_one_or_none()
        return supervisor_id == reviewer_id


class LegacyAuditAdapter:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(self, request: AuditRequest) -> None:
        await audit_service.audit(
            self._session,
            actor_id=request.actor_id,
            actor_role=request.actor_role,
            action=request.action,
            summary=request.summary,
            target_type=request.target_type,
            target_id=request.target_id,
        )


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class UUIDIdentifier:
    def new_id(self) -> uuid.UUID:
        return uuid.uuid4()
