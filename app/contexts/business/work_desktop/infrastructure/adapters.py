"""Read-model and published-capability adapters for Work Desktop."""

from __future__ import annotations

import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.business.collaboration_requests import public as collaboration_requests
from app.contexts.business.group_messaging import public as group_messaging
from app.contexts.business.proposal_management import public as proposal_management
from app.contexts.business.work_desktop.application.contracts import (
    CollaborationProjection,
    DeliverableProjection,
    DesktopPrincipal,
    ProposalProjection,
    ResolutionProjection,
    TaskProjection,
)
from app.contexts.foundations.access_control import public as access_control
from app.contexts.foundations.identity import public as identity
from app.contexts.foundations.identity.contracts import Principal, PrincipalType
from app.contexts.foundations.knowledge.storage_gateway import get_object_bytes
from app.models.deliverable import Deliverable
from app.models.meeting import MeetingResolution
from app.models.task import TaskCard

_REPORTED = "reported"
_ACCEPTED = "accepted"
_CANCELLED = "cancelled"
_REVIEWED = "reviewed"


class SQLAlchemyTaskDashboardAdapter:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _projection(row: TaskCard) -> TaskProjection:
        return TaskProjection(
            id=row.id,
            title=row.title,
            task_type=row.task_type,
            status=row.status,
            priority=row.priority,
            create_time=row.create_time,
        )

    async def reported_for(
        self, principal: DesktopPrincipal, *, limit: int
    ) -> tuple[TaskProjection, ...]:
        filters = [TaskCard.status == _REPORTED, TaskCard.is_delete.is_(False)]
        if not principal.is_admin:
            filters.append(
                or_(
                    TaskCard.creator_id == principal.id,
                    TaskCard.assignee_user_id == principal.id,
                )
            )
        rows = (
            await self._session.execute(
                select(TaskCard).where(*filters).order_by(TaskCard.create_time.desc()).limit(limit)
            )
        ).scalars()
        return tuple(self._projection(row) for row in rows)

    async def active_for(
        self, principal: DesktopPrincipal, *, limit: int
    ) -> tuple[TaskProjection, ...]:
        rows = (
            await self._session.execute(
                select(TaskCard)
                .where(
                    or_(
                        TaskCard.creator_id == principal.id,
                        TaskCard.assignee_user_id == principal.id,
                    ),
                    TaskCard.status.not_in((_ACCEPTED, _CANCELLED)),
                    TaskCard.is_delete.is_(False),
                )
                .order_by(TaskCard.create_time.desc())
                .limit(limit)
            )
        ).scalars()
        return tuple(self._projection(row) for row in rows)


class PublishedProposalQueueAdapter:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def reviewed(self, *, limit: int) -> tuple[ProposalProjection, ...]:
        rows = await proposal_management.list_proposals(
            self._session,
            status=_REVIEWED,
            limit=limit,
        )
        return tuple(
            ProposalProjection(
                id=row.id,
                title=row.title,
                code=row.code,
                priority=row.priority,
                create_time=row.create_time,
            )
            for row in rows
        )


class SQLAlchemyResolutionQueueAdapter:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def unconfirmed(self, *, limit: int) -> tuple[ResolutionProjection, ...]:
        rows = (
            await self._session.execute(
                select(MeetingResolution)
                .where(
                    MeetingResolution.is_confirmed.is_(False),
                    MeetingResolution.is_delete.is_(False),
                )
                .order_by(MeetingResolution.create_time.desc())
                .limit(limit)
            )
        ).scalars()
        return tuple(
            ResolutionProjection(
                id=row.id,
                content=row.content,
                due_date=row.due_date,
                create_time=row.create_time,
            )
            for row in rows
        )


class PublishedCollaborationQueueAdapter:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def review_queue(
        self, principal: DesktopPrincipal
    ) -> tuple[CollaborationProjection, ...]:
        rows = await collaboration_requests.review_queue(
            self._session,
            supervisor_user_id=principal.id,
            is_admin=principal.is_admin,
        )
        return tuple(
            CollaborationProjection(
                id=row.id,
                title=row.title,
                risk_level=row.risk_level,
                create_time=row.create_time,
            )
            for row in rows
        )


class PublishedChannelCounterAdapter:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def count(self) -> int:
        return len(await group_messaging.list_channels(self._session))


class PublishedKnowledgeCounterAdapter:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def count_for(self, principal: DesktopPrincipal) -> int:
        ids = await access_control.visible_knowledge_ids(
            self._session,
            principal=Principal(
                principal_type=PrincipalType.USER,
                principal_id=principal.id,
                role_code=principal.role_code,
                department_id=principal.department_id,
            ),
        )
        return len(ids)


class PublishedIdentityDirectoryAdapter:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: uuid.UUID) -> DesktopPrincipal | None:
        row = await identity.get_user_by_id(self._session, user_id=user_id)
        if row is None:
            return None
        return DesktopPrincipal(
            id=row.id,
            display_name=row.real_name or row.username,
            role_code=row.role_code,
            department_id=row.department_id,
            is_deleted=row.is_delete,
        )


class SQLAlchemyDeliverableInboxAdapter:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _projection(row: Deliverable) -> DeliverableProjection:
        return DeliverableProjection(
            id=row.id,
            owner_user_id=row.owner_user_id,
            file_name=row.file_name,
            file_format=row.file_format,
            agent_name=row.agent_name,
            file_size=row.file_size,
            storage_path=row.storage_path,
            create_time=row.create_time,
            is_deleted=row.is_delete,
        )

    async def list_for(
        self, owner_user_id: uuid.UUID, *, limit: int
    ) -> tuple[DeliverableProjection, ...]:
        rows = (
            await self._session.execute(
                select(Deliverable)
                .where(
                    Deliverable.owner_user_id == owner_user_id,
                    Deliverable.is_delete.is_(False),
                )
                .order_by(Deliverable.create_time.desc())
                .limit(limit)
            )
        ).scalars()
        return tuple(self._projection(row) for row in rows)

    async def get(self, deliverable_id: uuid.UUID) -> DeliverableProjection | None:
        row = await self._session.get(Deliverable, deliverable_id)
        return self._projection(row) if row is not None else None


class KnowledgeObjectStorageAdapter:
    async def get_object_bytes(self, object_name: str) -> bytes:
        return await get_object_bytes(object_name)
