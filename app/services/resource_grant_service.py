"""资源授权例外管理（docs/13 §1.3 · F4b）：grant/revoke/list + 授权推导。

红线：grant 只授内容访问权，绝不授生效权。部门授权覆盖其子树（读时按祖先链判定）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.shared_kernel import ResourceNotFound, RuleViolation
from app.knowledge.scope import ancestor_dept_ids
from app.models.resource_grant import (
    GRANTEE_DEPARTMENT,
    GRANTEE_USER,
    PERM_ADMIN,
    PERM_READ,
    PERM_WRITE,
    ResourceGrant,
)
from app.models.system import SysUser

_VALID_GRANTEE = (GRANTEE_USER, "agent", GRANTEE_DEPARTMENT)
_VALID_PERM = (PERM_READ, PERM_WRITE, PERM_ADMIN)


def _naive(dt: datetime) -> datetime:
    """去 tz 便于跨库（PG aware / sqlite naive）比较。# ponytail: tz 边界近似，授权过期够用。"""
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


async def get_grant(db: AsyncSession, grant_id: uuid.UUID) -> ResourceGrant:
    g = await db.get(ResourceGrant, grant_id)
    if g is None or g.is_delete:
        raise ResourceNotFound("授权记录不存在")
    return g


async def create_grant(
    db: AsyncSession,
    *,
    resource_type: str,
    resource_id: uuid.UUID,
    grantee_type: str,
    grantee_id: uuid.UUID,
    perm: str = PERM_READ,
    granted_by: uuid.UUID | None,
    expires_at: datetime | None = None,
) -> ResourceGrant:
    if grantee_type not in _VALID_GRANTEE:
        raise RuleViolation(f"grantee_type 仅支持 {'/'.join(_VALID_GRANTEE)}")
    if perm not in _VALID_PERM:
        raise RuleViolation(f"perm 仅支持 {'/'.join(_VALID_PERM)}")
    g = ResourceGrant(
        resource_type=resource_type, resource_id=resource_id,
        grantee_type=grantee_type, grantee_id=grantee_id,
        perm=perm, granted_by=granted_by, expires_at=expires_at,
    )
    db.add(g)
    await db.commit()
    await db.refresh(g)
    return g


async def revoke_grant(db: AsyncSession, grant_id: uuid.UUID) -> None:
    g = await get_grant(db, grant_id)
    g.is_delete = True
    await db.commit()


async def list_grants(
    db: AsyncSession,
    *,
    resource_type: str | None = None,
    grantee_id: uuid.UUID | None = None,
) -> list[dict[str, Any]]:
    stmt = select(ResourceGrant).where(ResourceGrant.is_delete.is_(False))
    if resource_type:
        stmt = stmt.where(ResourceGrant.resource_type == resource_type)
    if grantee_id:
        stmt = stmt.where(ResourceGrant.grantee_id == grantee_id)
    stmt = stmt.order_by(ResourceGrant.create_time.desc())
    return [
        {
            "id": str(g.id), "resource_type": g.resource_type,
            "resource_id": str(g.resource_id), "grantee_type": g.grantee_type,
            "grantee_id": str(g.grantee_id), "perm": g.perm,
            "granted_by": str(g.granted_by) if g.granted_by else None,
            "expires_at": g.expires_at.isoformat() if g.expires_at else None,
            "create_time": g.create_time.isoformat(),
        }
        for g in (await db.execute(stmt)).scalars()
    ]


async def granted_resource_ids(
    db: AsyncSession, user: SysUser, resource_type: str
) -> list[uuid.UUID]:
    """某真人经 grant 显式获得访问的资源 id 集（本人直授 ∪ 所在部门子树授权，未过期）。"""
    ancestors = await ancestor_dept_ids(db, user.department_id)
    conds = [
        (ResourceGrant.grantee_type == GRANTEE_USER) & (ResourceGrant.grantee_id == user.id)
    ]
    if ancestors:
        conds.append(
            (ResourceGrant.grantee_type == GRANTEE_DEPARTMENT)
            & (ResourceGrant.grantee_id.in_(ancestors))
        )
    stmt = select(ResourceGrant).where(
        ResourceGrant.resource_type == resource_type,
        ResourceGrant.is_delete.is_(False),
        or_(*conds),
    )
    now = datetime.now(UTC).replace(tzinfo=None)
    return [
        g.resource_id
        for g in (await db.execute(stmt)).scalars()
        if g.expires_at is None or _naive(g.expires_at) > now
    ]


async def granted_kb_ids(db: AsyncSession, user: SysUser) -> list[uuid.UUID]:
    """某真人经 grant 可访问的知识库 id 集（接 scope.resolve_visible_kb_ids 的 extra_kb_ids）。"""
    return await granted_resource_ids(db, user, "knowledge_base")
