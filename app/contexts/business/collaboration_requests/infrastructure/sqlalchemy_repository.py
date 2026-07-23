"""SQLAlchemy mapper and repository for existing collaboration tables."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.business.collaboration_requests.domain.models import (
    CollaborationAuthorization,
    CollaborationRequest,
)
from app.models.collab import (
    REQ_PENDING,
    CollabAuthorization,
    CollabRequest,
)


def authorization_to_domain(row: CollabAuthorization) -> CollaborationAuthorization:
    return CollaborationAuthorization(
        id=row.id,
        source_department_id=row.source_department_id,
        target_department_id=row.target_department_id,
        collab_type=row.collab_type,
        authorized_by=row.authorized_by,
        is_active=row.is_active,
        create_time=row.create_time,
        is_deleted=row.is_delete,
    )


def request_to_domain(row: CollabRequest) -> CollaborationRequest:
    return CollaborationRequest(
        id=row.id,
        source_department_id=row.source_department_id,
        target_department_id=row.target_department_id,
        title=row.title,
        summary=row.summary,
        category=row.category,
        risk_level=row.risk_level,
        status=row.status,
        requested_by=row.requested_by,
        reviewed_by=row.reviewed_by,
        review_note=row.review_note,
        ref_type=row.ref_type,
        ref_id=row.ref_id,
        idempotency_key=row.idempotency_key,
        create_time=row.create_time,
    )


class SQLAlchemyCollaborationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._authorizations: dict[uuid.UUID, CollabAuthorization] = {}
        self._requests: dict[uuid.UUID, CollabRequest] = {}

    async def add_authorization(
        self, authorization: CollaborationAuthorization
    ) -> None:
        row = CollabAuthorization(
            id=authorization.id,
            source_department_id=authorization.source_department_id,
            target_department_id=authorization.target_department_id,
            collab_type=authorization.collab_type,
            authorized_by=authorization.authorized_by,
            is_active=authorization.is_active,
            create_time=authorization.create_time,
        )
        self._session.add(row)
        await self._session.flush()
        self._authorizations[row.id] = row

    async def get_authorization(
        self, authorization_id: uuid.UUID
    ) -> CollaborationAuthorization | None:
        row = await self._session.get(CollabAuthorization, authorization_id)
        if row is None or row.is_delete:
            return None
        self._authorizations[row.id] = row
        return authorization_to_domain(row)

    async def save_authorization(
        self, authorization: CollaborationAuthorization
    ) -> None:
        row = self._authorizations.get(authorization.id)
        if row is None:
            row = await self._session.get(CollabAuthorization, authorization.id)
        if row is None:
            return
        row.is_active = authorization.is_active
        row.is_delete = authorization.is_deleted
        await self._session.flush()
        self._authorizations[row.id] = row

    async def list_authorizations(
        self, *, target_department_id: uuid.UUID | None
    ) -> list[CollaborationAuthorization]:
        stmt = select(CollabAuthorization).where(CollabAuthorization.is_delete.is_(False))
        if target_department_id is not None:
            stmt = stmt.where(
                CollabAuthorization.target_department_id == target_department_id
            )
        stmt = stmt.order_by(CollabAuthorization.create_time.desc())
        rows = list((await self._session.execute(stmt)).scalars())
        self._authorizations.update({row.id: row for row in rows})
        return [authorization_to_domain(row) for row in rows]

    async def has_authorization(
        self,
        *,
        source_department_id: uuid.UUID,
        target_department_id: uuid.UUID,
        collab_type: str,
    ) -> bool:
        stmt = select(CollabAuthorization.id).where(
            CollabAuthorization.source_department_id == source_department_id,
            CollabAuthorization.target_department_id == target_department_id,
            CollabAuthorization.collab_type == collab_type,
            CollabAuthorization.is_active.is_(True),
            CollabAuthorization.is_delete.is_(False),
        )
        return (await self._session.execute(stmt)).first() is not None

    async def add_request(self, request: CollaborationRequest) -> None:
        row = CollabRequest(
            id=request.id,
            source_department_id=request.source_department_id,
            target_department_id=request.target_department_id,
            title=request.title,
            summary=request.summary,
            category=request.category,
            risk_level=request.risk_level,
            status=request.status,
            requested_by=request.requested_by,
            reviewed_by=request.reviewed_by,
            review_note=request.review_note,
            ref_type=request.ref_type,
            ref_id=request.ref_id,
            idempotency_key=request.idempotency_key,
            create_time=request.create_time,
        )
        self._session.add(row)
        await self._session.flush()
        self._requests[row.id] = row

    async def get_request(self, request_id: uuid.UUID) -> CollaborationRequest | None:
        row = await self._session.get(CollabRequest, request_id)
        if row is None or row.is_delete:
            return None
        self._requests[row.id] = row
        return request_to_domain(row)

    async def get_request_by_idempotency_key(
        self, idempotency_key: str
    ) -> CollaborationRequest | None:
        row = (
            await self._session.execute(
                select(CollabRequest).where(
                    CollabRequest.idempotency_key == idempotency_key,
                    CollabRequest.is_delete.is_(False),
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        self._requests[row.id] = row
        return request_to_domain(row)

    async def save_request(self, request: CollaborationRequest) -> None:
        row = self._requests.get(request.id)
        if row is None:
            row = await self._session.get(CollabRequest, request.id)
        if row is None or row.is_delete:
            return
        row.status = request.status
        row.reviewed_by = request.reviewed_by
        row.review_note = request.review_note
        row.ref_type = request.ref_type
        row.ref_id = request.ref_id
        await self._session.flush()
        self._requests[row.id] = row

    async def list_pending_requests(
        self, *, target_department_ids: tuple[uuid.UUID, ...] | None
    ) -> list[CollaborationRequest]:
        stmt = select(CollabRequest).where(CollabRequest.status == REQ_PENDING)
        if target_department_ids is not None:
            if not target_department_ids:
                return []
            stmt = stmt.where(CollabRequest.target_department_id.in_(target_department_ids))
        stmt = stmt.order_by(CollabRequest.create_time)
        rows = list((await self._session.execute(stmt)).scalars())
        self._requests.update({row.id: row for row in rows})
        return [request_to_domain(row) for row in rows]
