"""Request-scoped Access Control operations for transport and integration callers."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.access_control.application.contracts import (
    CreateGrantCommand,
    GrantResult,
    ListGrantsQuery,
)
from app.contexts.foundations.access_control.contracts import (
    PolicyDecision,
    ResourceReadPolicyRequest,
)
from app.contexts.foundations.access_control.infrastructure.composition import (
    build_access_control_application,
)
from app.contexts.foundations.identity.contracts import Principal


async def get_grant(session: AsyncSession, grant_id: uuid.UUID) -> GrantResult:
    return await build_access_control_application(session).get_grant(grant_id)


async def create_grant(
    session: AsyncSession,
    *,
    resource_type: str,
    resource_id: uuid.UUID,
    grantee_type: str,
    grantee_id: uuid.UUID,
    permission: str = "read",
    granted_by: uuid.UUID | None = None,
    expires_at: datetime | None = None,
) -> GrantResult:
    return await build_access_control_application(session).create_grant(
        CreateGrantCommand(
            resource_type=resource_type,
            resource_id=resource_id,
            grantee_type=grantee_type,
            grantee_id=grantee_id,
            permission=permission,
            granted_by=granted_by,
            expires_at=expires_at,
        )
    )


async def revoke_grant(session: AsyncSession, grant_id: uuid.UUID) -> None:
    await build_access_control_application(session).revoke_grant(grant_id)


async def list_grants(
    session: AsyncSession,
    *,
    resource_type: str | None,
    grantee_id: uuid.UUID | None,
) -> tuple[GrantResult, ...]:
    return await build_access_control_application(session).list_grants(
        ListGrantsQuery(resource_type=resource_type, grantee_id=grantee_id)
    )


async def granted_resource_ids(
    session: AsyncSession,
    *,
    principal: Principal,
    resource_type: str,
) -> tuple[uuid.UUID, ...]:
    return await build_access_control_application(session).granted_resource_ids(
        principal,
        resource_type,
    )


async def visible_knowledge_ids(
    session: AsyncSession,
    *,
    principal: Principal,
) -> tuple[uuid.UUID, ...]:
    return await build_access_control_application(session).visible_knowledge_ids(principal)


async def decide_resource_read(
    session: AsyncSession,
    request: ResourceReadPolicyRequest,
) -> PolicyDecision:
    return await build_access_control_application(session).decide_resource_read(request)
