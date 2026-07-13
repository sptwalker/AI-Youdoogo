"""资源授权接口（F4b，仅 admin）：显式跨节点/私有覆盖授权。

红线：grant 只授内容访问权（read/write/admin），绝不授生效权。授权/撤权=权限变更，落审计。
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_roles
from app.core.database import get_db
from app.core.exceptions import ok
from app.models.system import SysUser
from app.services import audit_service, resource_grant_service

router = APIRouter(prefix="/resource-grants", tags=["permission"])

DB = Annotated[AsyncSession, Depends(get_db)]
Admin = Annotated[SysUser, Depends(require_roles("admin"))]


class GrantCreate(BaseModel):
    """授权：把某资源的访问权授予某 user/agent/department。"""

    resource_type: str = Field(pattern="^(knowledge_base|data_source)$")
    resource_id: uuid.UUID
    grantee_type: str = Field(pattern="^(user|agent|department)$")
    grantee_id: uuid.UUID
    perm: str = Field(default="read", pattern="^(read|write|admin)$")
    expires_at: datetime | None = None


@router.get("")
async def list_grants(
    db: DB,
    _: Admin,
    resource_type: Annotated[str | None, Query()] = None,
    grantee_id: Annotated[uuid.UUID | None, Query()] = None,
) -> dict:
    """授权列表（可按资源类型/被授方过滤）。"""
    return ok(
        await resource_grant_service.list_grants(
            db, resource_type=resource_type, grantee_id=grantee_id
        )
    )


@router.post("")
async def create_grant(body: GrantCreate, db: DB, admin: Admin) -> dict:
    """新增授权 → 落权限变更审计。"""
    g = await resource_grant_service.create_grant(
        db,
        resource_type=body.resource_type, resource_id=body.resource_id,
        grantee_type=body.grantee_type, grantee_id=body.grantee_id,
        perm=body.perm, granted_by=admin.id, expires_at=body.expires_at,
    )
    await audit_service.audit(
        db, actor_id=admin.id, actor_role=admin.role_code, action="grant.create",
        summary=f"授权 {body.resource_type} → {body.grantee_type}",
        target_type=body.resource_type, target_id=body.resource_id,
        detail={"grantee_id": str(body.grantee_id), "perm": body.perm},
    )
    return ok({"id": str(g.id)})


@router.delete("/{grant_id}")
async def revoke_grant(grant_id: uuid.UUID, db: DB, admin: Admin) -> dict:
    """撤销授权 → 落权限变更审计。"""
    await resource_grant_service.revoke_grant(db, grant_id)
    await audit_service.audit(
        db, actor_id=admin.id, actor_role=admin.role_code, action="grant.revoke",
        summary="撤销授权", target_type="resource_grant", target_id=grant_id,
    )
    return ok()
