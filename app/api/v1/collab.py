"""跨部门协作治理接口（F4c）：既定工作流授权 + 主管复核队列。

授权（admin）；发起请求（任意登录）；复核队列/复核（目标部门主管或 admin）。
红线：复核=分发闸门；产出生效仍走真人验收。授权/复核落审计。
"""

import uuid
from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, require_roles
from app.contexts.business.collaboration_requests.application.contracts import (
    CollaborationAuthorizationResult,
    CollaborationRequestResult,
)
from app.contexts.business.collaboration_requests.application.errors import (
    CollaborationAuthorizationNotFound,
    CollaborationRequestNotFound,
    CollaborationReviewForbidden,
)
from app.contexts.business.collaboration_requests.domain.errors import (
    CollaborationRequestError,
)
from app.contexts.business.collaboration_requests.entrypoints import operations
from app.contexts.foundations.identity.application.contracts import IdentityUserResult
from app.contexts.shared_kernel import PermissionDenied, ResourceNotFound, RuleViolation
from app.core.database import get_db
from app.platform.http_runtime import ok

router = APIRouter(tags=["collab"])

DB = Annotated[AsyncSession, Depends(get_db)]
Admin = Annotated[IdentityUserResult, Depends(require_roles("admin"))]


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


def _authorization_data(item: CollaborationAuthorizationResult) -> dict:
    return {
        "id": str(item.id),
        "source_department_id": str(item.source_department_id),
        "target_department_id": str(item.target_department_id),
        "collab_type": item.collab_type,
        "is_active": item.is_active,
    }


def _request_data(item: CollaborationRequestResult) -> dict:
    return {
        "id": str(item.id),
        "source_department_id": (
            str(item.source_department_id) if item.source_department_id else None
        ),
        "target_department_id": str(item.target_department_id),
        "title": item.title,
        "summary": item.summary,
        "category": item.category,
        "risk_level": item.risk_level,
        "status": item.status,
        "requested_by": str(item.requested_by) if item.requested_by else None,
        "reviewed_by": str(item.reviewed_by) if item.reviewed_by else None,
        "review_note": item.review_note,
        "create_time": item.create_time.isoformat(),
    }


def _raise_transport_error(exc: CollaborationRequestError) -> NoReturn:
    if isinstance(exc, (CollaborationAuthorizationNotFound, CollaborationRequestNotFound)):
        raise ResourceNotFound(str(exc)) from exc
    if isinstance(exc, CollaborationReviewForbidden):
        raise PermissionDenied(str(exc)) from exc
    raise RuleViolation(str(exc)) from exc


# ---- 既定工作流授权（admin） ----

@router.post("/collab-authorizations")
async def create_authorization(body: AuthorizeCreate, db: DB, admin: Admin) -> dict:
    """目标部门预授权源部门某类协作通道。"""
    a = await operations.authorize(
        db,
        source_department_id=body.source_department_id,
        target_department_id=body.target_department_id,
        collab_type=body.collab_type,
        authorized_by=admin.id,
        actor_role=admin.role_code,
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
        [
            _authorization_data(item)
            for item in await operations.list_authorizations(
                db,
                target_department_id=target_department_id,
            )
        ]
    )


@router.delete("/collab-authorizations/{auth_id}")
async def revoke_authorization(auth_id: uuid.UUID, db: DB, admin: Admin) -> dict:
    """撤销既定工作流授权。"""
    try:
        await operations.revoke_authorization(
            db,
            auth_id,
            actor_id=admin.id,
            actor_role=admin.role_code,
        )
    except CollaborationRequestError as exc:
        _raise_transport_error(exc)
    return ok()


# ---- 主管复核队列 ----

@router.post("/collab-requests")
async def create_request(body: RequestCreate, db: DB, user: CurrentUser) -> dict:
    """发起跨部门协作请求入复核队列。"""
    r = await operations.create_request(
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
        [
            _request_data(item)
            for item in await operations.review_queue(
                db,
                supervisor_user_id=user.id,
                is_admin=user.role_code == "admin",
            )
        ]
    )


@router.post("/collab-requests/{request_id}/review")
async def review_request(
    request_id: uuid.UUID, body: ReviewRequest, db: DB, user: CurrentUser
) -> dict:
    """复核 approve/reject（仅目标部门主管或 admin；红线：仅分发闸门）。"""
    try:
        r = await operations.review_request_authorized(
            db,
            request_id,
            decision=body.decision,
            reviewer_id=user.id,
            reviewer_role=user.role_code,
            note=body.note,
        )
    except CollaborationRequestError as exc:
        _raise_transport_error(exc)
    return ok({"id": str(r.id), "status": r.status})
