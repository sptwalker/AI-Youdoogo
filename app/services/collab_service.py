"""One-way compatibility facade for Collaboration Requests."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.business.collaboration_requests.application.contracts import (
    CollaborationAuthorizationResult,
    CollaborationRequestResult,
)
from app.contexts.business.collaboration_requests.application.errors import (
    CollaborationAuthorizationNotFound,
    CollaborationRequestNotFound,
)
from app.contexts.business.collaboration_requests.domain.errors import (
    CollaborationReviewNotAllowed,
    InvalidReviewDecision,
)
from app.contexts.business.collaboration_requests.domain.models import classify_risk
from app.contexts.business.collaboration_requests.entrypoints import operations
from app.contexts.shared_kernel import ResourceNotFound, RuleViolation

__all__ = [
    "authorize",
    "classify_risk",
    "create_request",
    "has_authorization",
    "list_authorizations",
    "review_queue",
    "review_request",
    "revoke_authorization",
]


def _authorization_dict(item: CollaborationAuthorizationResult) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "source_department_id": str(item.source_department_id),
        "target_department_id": str(item.target_department_id),
        "collab_type": item.collab_type,
        "is_active": item.is_active,
    }


def _request_dict(item: CollaborationRequestResult) -> dict[str, Any]:
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


async def authorize(
    db: AsyncSession,
    *,
    source_department_id: uuid.UUID,
    target_department_id: uuid.UUID,
    collab_type: str,
    authorized_by: uuid.UUID | None,
) -> CollaborationAuthorizationResult:
    return await operations.authorize(
        db,
        source_department_id=source_department_id,
        target_department_id=target_department_id,
        collab_type=collab_type,
        authorized_by=authorized_by,
    )


async def revoke_authorization(db: AsyncSession, auth_id: uuid.UUID) -> None:
    try:
        await operations.revoke_authorization(db, auth_id)
    except CollaborationAuthorizationNotFound as exc:
        raise ResourceNotFound(str(exc)) from exc


async def list_authorizations(
    db: AsyncSession, *, target_department_id: uuid.UUID | None = None
) -> list[dict[str, Any]]:
    items = await operations.list_authorizations(
        db,
        target_department_id=target_department_id,
    )
    return [_authorization_dict(item) for item in items]


async def has_authorization(
    db: AsyncSession,
    *,
    source_department_id: uuid.UUID,
    target_department_id: uuid.UUID,
    collab_type: str,
) -> bool:
    return await operations.has_authorization(
        db,
        source_department_id=source_department_id,
        target_department_id=target_department_id,
        collab_type=collab_type,
    )


async def create_request(
    db: AsyncSession,
    *,
    target_department_id: uuid.UUID,
    title: str,
    source_department_id: uuid.UUID | None = None,
    summary: str | None = None,
    category: str | None = None,
    risk_level: str | None = None,
    requested_by: uuid.UUID | None = None,
    idempotency_key: str | None = None,
) -> CollaborationRequestResult:
    return await operations.create_request(
        db,
        target_department_id=target_department_id,
        title=title,
        source_department_id=source_department_id,
        summary=summary,
        category=category,
        risk_level=risk_level,
        requested_by=requested_by,
        idempotency_key=idempotency_key,
    )


async def review_queue(
    db: AsyncSession,
    *,
    supervisor_user_id: uuid.UUID,
    is_admin: bool = False,
) -> list[dict[str, Any]]:
    items = await operations.review_queue(
        db,
        supervisor_user_id=supervisor_user_id,
        is_admin=is_admin,
    )
    return [_request_dict(item) for item in items]


async def review_request(
    db: AsyncSession,
    request_id: uuid.UUID,
    *,
    decision: str,
    reviewer_id: uuid.UUID,
    note: str | None = None,
) -> CollaborationRequestResult:
    try:
        return await operations.review_request(
            db,
            request_id,
            decision=decision,
            reviewer_id=reviewer_id,
            note=note,
        )
    except CollaborationRequestNotFound as exc:
        raise ResourceNotFound(str(exc)) from exc
    except (CollaborationReviewNotAllowed, InvalidReviewDecision) as exc:
        raise RuleViolation(str(exc)) from exc
