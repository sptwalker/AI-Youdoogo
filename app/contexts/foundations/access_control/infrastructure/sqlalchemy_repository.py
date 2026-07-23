"""SQLAlchemy adapter for Access Control-owned explicit grants."""

from __future__ import annotations

import uuid

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.access_control.domain.models import (
    GranteeType,
    GrantTarget,
    PermissionLevel,
    ResourceGrantRecord,
)
from app.models.resource_grant import ResourceGrant


def _to_domain(row: ResourceGrant) -> ResourceGrantRecord:
    return ResourceGrantRecord(
        id=row.id,
        resource_type=row.resource_type,
        resource_id=row.resource_id,
        grantee_type=GranteeType(row.grantee_type),
        grantee_id=row.grantee_id,
        permission=PermissionLevel(row.perm),
        granted_by=row.granted_by,
        expires_at=row.expires_at,
        create_time=row.create_time,
        is_deleted=row.is_delete,
    )


def _from_domain(grant: ResourceGrantRecord) -> ResourceGrant:
    return ResourceGrant(
        id=grant.id,
        resource_type=grant.resource_type,
        resource_id=grant.resource_id,
        grantee_type=grant.grantee_type.value,
        grantee_id=grant.grantee_id,
        perm=grant.permission.value,
        granted_by=grant.granted_by,
        expires_at=grant.expires_at,
        create_time=grant.create_time,
        is_delete=grant.is_deleted,
    )


class SQLAlchemyGrantRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._rows: dict[uuid.UUID, ResourceGrant] = {}

    async def get(self, grant_id: uuid.UUID) -> ResourceGrantRecord | None:
        row = await self._session.get(ResourceGrant, grant_id)
        if row is None:
            return None
        self._rows[grant_id] = row
        return _to_domain(row)

    async def add(self, grant: ResourceGrantRecord) -> None:
        row = _from_domain(grant)
        self._rows[grant.id] = row
        self._session.add(row)

    async def save(self, grant: ResourceGrantRecord) -> None:
        row = self._rows.get(grant.id)
        if row is None:
            row = await self._session.get(ResourceGrant, grant.id)
        if row is None:
            return
        self._rows[grant.id] = row
        row.resource_type = grant.resource_type
        row.resource_id = grant.resource_id
        row.grantee_type = grant.grantee_type.value
        row.grantee_id = grant.grantee_id
        row.perm = grant.permission.value
        row.granted_by = grant.granted_by
        row.expires_at = grant.expires_at
        row.is_delete = grant.is_deleted

    async def list_records(
        self,
        *,
        resource_type: str | None,
        grantee_id: uuid.UUID | None,
    ) -> list[ResourceGrantRecord]:
        stmt = select(ResourceGrant).where(ResourceGrant.is_delete.is_(False))
        if resource_type:
            stmt = stmt.where(ResourceGrant.resource_type == resource_type)
        if grantee_id:
            stmt = stmt.where(ResourceGrant.grantee_id == grantee_id)
        stmt = stmt.order_by(ResourceGrant.create_time.desc())
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_to_domain(row) for row in rows]

    async def find_for_targets(
        self,
        *,
        resource_type: str,
        targets: tuple[GrantTarget, ...],
    ) -> list[ResourceGrantRecord]:
        target_conditions = [
            and_(
                ResourceGrant.grantee_type == target.grantee_type.value,
                ResourceGrant.grantee_id == target.grantee_id,
            )
            for target in targets
        ]
        stmt = select(ResourceGrant).where(
            ResourceGrant.resource_type == resource_type,
            ResourceGrant.is_delete.is_(False),
            or_(*target_conditions),
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_to_domain(row) for row in rows]
