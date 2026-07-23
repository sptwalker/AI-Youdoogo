"""Plain request-scoped operations used by compatibility and HTTP adapters."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.business.collaboration_requests.application.contracts import (
    AuthorizeCollaborationCommand,
    CollaborationAuthorizationResult,
    CollaborationRequestResult,
    CollaborationReviewPrincipal,
    CollaborationReviewQueueQuery,
    CreateCollaborationRequestCommand,
    HasCollaborationAuthorizationQuery,
    ListCollaborationAuthorizationsQuery,
    ReviewCollaborationRequestCommand,
    RevokeCollaborationAuthorizationCommand,
)
from app.contexts.business.collaboration_requests.infrastructure.composition import (
    build_collaboration_requests_application,
)


async def authorize(
    session: AsyncSession,
    *,
    source_department_id: uuid.UUID,
    target_department_id: uuid.UUID,
    collab_type: str,
    authorized_by: uuid.UUID | None,
    actor_role: str | None = None,
) -> CollaborationAuthorizationResult:
    return await build_collaboration_requests_application(session).authorize(
        AuthorizeCollaborationCommand(
            source_department_id=source_department_id,
            target_department_id=target_department_id,
            collab_type=collab_type,
            authorized_by=authorized_by,
            actor_role=actor_role,
        )
    )


async def revoke_authorization(
    session: AsyncSession,
    auth_id: uuid.UUID,
    *,
    actor_id: uuid.UUID | None = None,
    actor_role: str | None = None,
) -> None:
    await build_collaboration_requests_application(session).revoke(
        RevokeCollaborationAuthorizationCommand(
            authorization_id=auth_id,
            actor_id=actor_id,
            actor_role=actor_role,
        )
    )


async def list_authorizations(
    session: AsyncSession, *, target_department_id: uuid.UUID | None = None
) -> tuple[CollaborationAuthorizationResult, ...]:
    return await build_collaboration_requests_application(session).list_authorizations(
        ListCollaborationAuthorizationsQuery(
            target_department_id=target_department_id
        )
    )


async def has_authorization(
    session: AsyncSession,
    *,
    source_department_id: uuid.UUID,
    target_department_id: uuid.UUID,
    collab_type: str,
) -> bool:
    return await build_collaboration_requests_application(session).has_authorization(
        HasCollaborationAuthorizationQuery(
            source_department_id=source_department_id,
            target_department_id=target_department_id,
            collab_type=collab_type,
        )
    )


async def create_request(
    session: AsyncSession,
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
    return await build_collaboration_requests_application(session).create_request(
        CreateCollaborationRequestCommand(
            target_department_id=target_department_id,
            title=title,
            source_department_id=source_department_id,
            summary=summary,
            category=category,
            risk_level=risk_level,
            requested_by=requested_by,
            idempotency_key=idempotency_key,
        )
    )


async def review_queue(
    session: AsyncSession,
    *,
    supervisor_user_id: uuid.UUID,
    is_admin: bool = False,
) -> tuple[CollaborationRequestResult, ...]:
    return await build_collaboration_requests_application(session).review_queue(
        CollaborationReviewQueueQuery(
            supervisor_user_id=supervisor_user_id,
            is_admin=is_admin,
        )
    )


async def review_request(
    session: AsyncSession,
    request_id: uuid.UUID,
    *,
    decision: str,
    reviewer_id: uuid.UUID,
    note: str | None = None,
    actor_role: str | None = None,
) -> CollaborationRequestResult:
    return await build_collaboration_requests_application(session).review_request(
        ReviewCollaborationRequestCommand(
            request_id=request_id,
            decision=decision,
            reviewer_id=reviewer_id,
            note=note,
            actor_role=actor_role,
        )
    )


async def review_request_authorized(
    session: AsyncSession,
    request_id: uuid.UUID,
    *,
    decision: str,
    reviewer_id: uuid.UUID,
    reviewer_role: str,
    note: str | None = None,
) -> CollaborationRequestResult:
    application = build_collaboration_requests_application(session)
    return await application.review_request_authorized(
        ReviewCollaborationRequestCommand(
            request_id=request_id,
            decision=decision,
            reviewer_id=reviewer_id,
            note=note,
            actor_role=reviewer_role,
        ),
        CollaborationReviewPrincipal(id=reviewer_id, role_code=reviewer_role),
    )
