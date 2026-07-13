"""跨部门协作治理接口（F4c）：既定工作流授权 + 主管复核队列。

授权（admin）；发起请求（任意登录）；复核队列/复核（目标部门主管或 admin）。
红线：复核=分发闸门；产出生效仍走真人验收。授权/复核落审计。
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, require_roles
from app.core.database import get_db
from app.core.exceptions import AppError, ok
from app.models.collab import CollabRequest
from app.models.system import SysDepartment, SysUser
from app.services import audit_service, collab_service

router = APIRouter(tags=["collab"])

DB = Annotated[AsyncSession, Depends(get_db)]
Admin = Annotated[SysUser, Depends(require_roles("admin"))]


class AuthorizeCreate(BaseModel):
    """既定工作流授权。"""

    source_department_id: uuid.UUID
    target_department_id: uuid.UUID
    collab_type: str = Field(min_length=1, max_length=64)


class RequestCreate(BaseModel):
    """发起跨部门协作请求（risk_level 省略时按 category 自动分级）。"""

    target_department_id: uuid.UUID
    title: str = Field(min_length=1, max_length=200)
    source_department_id: uuid.UUID | None = None
    summary: str | None = None
    category: str | None = Field(default=None, max_length=64)
    risk_level: str | None = Field(default=None, pattern="^(low|high)$")


class ReviewRequest(BaseModel):
    """主管复核。"""

    decision: str = Field(pattern="^(approve|reject)$")
    note: str | None = None


# ---- 既定工作流授权（admin） ----

@router.post("/collab-authorizations")
async def create_authorization(body: AuthorizeCreate, db: DB, admin: Admin) -> dict:
    """目标部门预授权源部门某类协作通道。"""
    a = await collab_service.authorize(
        db,
        source_department_id=body.source_department_id,
        target_department_id=body.target_department_id,
        collab_type=body.collab_type, authorized_by=admin.id,
    )
    await audit_service.audit(
        db, actor_id=admin.id, actor_role=admin.role_code, action="collab.authorize",
        summary=f"授权跨部门协作 {body.collab_type}",
        target_type="collab_authorization", target_id=a.id,
    )
    return ok({"id": str(a.id)})


@router.get("/collab-authorizations")
async def list_authorizations(
    db: DB,
    _: CurrentUser,
    target_department_id: Annotated[uuid.UUID | None, Query()] = None,
) -> dict:
    """既定工作流授权列表。"""
    return ok(
        await collab_service.list_authorizations(db, target_department_id=target_department_id)
    )


@router.delete("/collab-authorizations/{auth_id}")
async def revoke_authorization(auth_id: uuid.UUID, db: DB, admin: Admin) -> dict:
    """撤销既定工作流授权。"""
    await collab_service.revoke_authorization(db, auth_id)
    await audit_service.audit(
        db, actor_id=admin.id, actor_role=admin.role_code, action="collab.revoke",
        summary="撤销跨部门协作授权",
        target_type="collab_authorization", target_id=auth_id,
    )
    return ok()


# ---- 主管复核队列 ----

@router.post("/collab-requests")
async def create_request(body: RequestCreate, db: DB, user: CurrentUser) -> dict:
    """发起跨部门协作请求入复核队列。"""
    r = await collab_service.create_request(
        db,
        target_department_id=body.target_department_id, title=body.title,
        source_department_id=body.source_department_id, summary=body.summary,
        category=body.category, risk_level=body.risk_level, requested_by=user.id,
    )
    return ok({"id": str(r.id), "risk_level": r.risk_level, "status": r.status})


@router.get("/collab-requests/review-queue")
async def get_review_queue(db: DB, user: CurrentUser) -> dict:
    """待我复核的跨部门协作请求（目标部门主管=本人；admin 见全部 pending）。"""
    return ok(
        await collab_service.review_queue(
            db, supervisor_user_id=user.id, is_admin=user.role_code == "admin"
        )
    )


@router.post("/collab-requests/{request_id}/review")
async def review_request(
    request_id: uuid.UUID, body: ReviewRequest, db: DB, user: CurrentUser
) -> dict:
    """复核 approve/reject（仅目标部门主管或 admin；红线：仅分发闸门）。"""
    r = await db.get(CollabRequest, request_id)
    if r is None or r.is_delete:
        raise AppError("协作请求不存在", code=404, status_code=404)
    if user.role_code != "admin":
        dept = await db.get(SysDepartment, r.target_department_id)
        if dept is None or dept.supervisor_user_id != user.id:
            raise AppError("仅目标部门主管或管理员可复核", code=403, status_code=403)
    r = await collab_service.review_request(
        db, request_id, decision=body.decision, reviewer_id=user.id, note=body.note
    )
    await audit_service.audit(
        db, actor_id=user.id, actor_role=user.role_code, action="collab.review",
        summary=f"复核跨部门协作 {r.title[:40]} → {r.status}",
        target_type="collab_request", target_id=r.id,
    )
    return ok({"id": str(r.id), "status": r.status})
