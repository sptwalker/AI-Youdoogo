"""SQLAlchemy mapper and repository for the existing Meeting tables."""

from __future__ import annotations

import uuid
from copy import deepcopy

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.business.meeting_management.application.ports import MeetingVisibility
from app.contexts.business.meeting_management.domain.models import (
    Discussion,
    Meeting,
    Resolution,
    Vote,
)
from app.models.meeting import (
    MeetingDiscuss,
    MeetingInfo,
    MeetingResolution,
    MeetingVote,
)


def _meeting_from_row(row: MeetingInfo) -> Meeting:
    return Meeting(
        id=row.id,
        title=row.title,
        meeting_type=row.meeting_type,
        status=row.status,
        creator_id=row.creator_id,
        participants=deepcopy(row.participants or []),
        department_id=row.department_id,
        scheduled_at=row.scheduled_at,
        summary=row.summary,
        create_time=row.create_time,
    )


def _discussion_from_row(row: MeetingDiscuss) -> Discussion:
    return Discussion(
        id=row.id,
        meeting_id=row.meeting_id,
        speaker_type=row.speaker_type,
        speaker_id=row.speaker_id,
        speaker_name=row.speaker_name,
        content=row.content,
        create_time=row.create_time,
    )


def _vote_from_row(row: MeetingVote) -> Vote:
    return Vote(
        id=row.id,
        meeting_id=row.meeting_id,
        subject=row.subject,
        voter_type=row.voter_type,
        voter_id=row.voter_id,
        choice=row.choice,
        comment=row.comment,
        create_time=row.create_time,
    )


def _resolution_from_row(row: MeetingResolution) -> Resolution:
    return Resolution(
        id=row.id,
        meeting_id=row.meeting_id,
        content=row.content,
        owner_id=row.owner_id,
        due_date=row.due_date,
        is_confirmed=row.is_confirmed,
        confirmed_by=row.confirmed_by,
        converted_task_id=row.converted_task_id,
        create_time=row.create_time,
    )


class SQLAlchemyMeetingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_meeting(self, meeting: Meeting) -> None:
        self._session.add(
            MeetingInfo(
                id=meeting.id,
                title=meeting.title,
                meeting_type=meeting.meeting_type,
                status=meeting.status,
                creator_id=meeting.creator_id,
                participants=deepcopy(meeting.participants),
                department_id=meeting.department_id,
                scheduled_at=meeting.scheduled_at,
                summary=meeting.summary,
                create_time=meeting.create_time,
            )
        )
        await self._session.flush()

    async def get_meeting(self, meeting_id: uuid.UUID) -> Meeting | None:
        row = await self._session.get(MeetingInfo, meeting_id)
        if row is None or row.is_delete:
            return None
        return _meeting_from_row(row)

    async def save_meeting(self, meeting: Meeting) -> None:
        row = await self._session.get(MeetingInfo, meeting.id)
        if row is None or row.is_delete:
            return
        row.title = meeting.title
        row.meeting_type = meeting.meeting_type
        row.status = meeting.status
        row.creator_id = meeting.creator_id
        row.participants = deepcopy(meeting.participants)
        row.department_id = meeting.department_id
        row.scheduled_at = meeting.scheduled_at
        row.summary = meeting.summary
        await self._session.flush()

    async def list_meetings(
        self,
        *,
        status: str | None,
        limit: int,
        visibility: MeetingVisibility,
    ) -> tuple[Meeting, ...]:
        statement = select(MeetingInfo).where(MeetingInfo.is_delete.is_(False))
        if status:
            statement = statement.where(MeetingInfo.status == status)
        if not visibility.unrestricted:
            conditions = [MeetingInfo.creator_id == visibility.creator_id]
            if visibility.department_id is not None:
                conditions.append(MeetingInfo.department_id == visibility.department_id)
            statement = statement.where(or_(*conditions))
        rows = (
            await self._session.execute(
                statement.order_by(MeetingInfo.create_time.desc()).limit(limit)
            )
        ).scalars()
        return tuple(_meeting_from_row(row) for row in rows)

    async def add_discussion(self, discussion: Discussion) -> None:
        self._session.add(
            MeetingDiscuss(
                id=discussion.id,
                meeting_id=discussion.meeting_id,
                speaker_type=discussion.speaker_type,
                speaker_id=discussion.speaker_id,
                speaker_name=discussion.speaker_name,
                content=discussion.content,
                create_time=discussion.create_time,
            )
        )
        await self._session.flush()

    async def list_discussions(self, meeting_id: uuid.UUID) -> tuple[Discussion, ...]:
        rows = (
            await self._session.execute(
                select(MeetingDiscuss)
                .where(MeetingDiscuss.meeting_id == meeting_id)
                .order_by(MeetingDiscuss.create_time)
            )
        ).scalars()
        return tuple(_discussion_from_row(row) for row in rows)

    async def add_vote(self, vote: Vote) -> None:
        self._session.add(
            MeetingVote(
                id=vote.id,
                meeting_id=vote.meeting_id,
                subject=vote.subject,
                voter_type=vote.voter_type,
                voter_id=vote.voter_id,
                choice=vote.choice,
                comment=vote.comment,
                create_time=vote.create_time,
            )
        )
        await self._session.flush()

    async def list_votes(self, meeting_id: uuid.UUID, subject: str) -> tuple[Vote, ...]:
        rows = (
            await self._session.execute(
                select(MeetingVote).where(
                    MeetingVote.meeting_id == meeting_id,
                    MeetingVote.subject == subject,
                )
            )
        ).scalars()
        return tuple(_vote_from_row(row) for row in rows)

    async def list_vote_subjects(self, meeting_id: uuid.UUID) -> tuple[str, ...]:
        rows = (
            await self._session.execute(
                select(MeetingVote.subject)
                .where(MeetingVote.meeting_id == meeting_id)
                .distinct()
                .order_by(MeetingVote.subject)
            )
        ).scalars()
        return tuple(rows)

    async def add_resolution(self, resolution: Resolution) -> None:
        self._session.add(
            MeetingResolution(
                id=resolution.id,
                meeting_id=resolution.meeting_id,
                content=resolution.content,
                owner_id=resolution.owner_id,
                due_date=resolution.due_date,
                is_confirmed=resolution.is_confirmed,
                confirmed_by=resolution.confirmed_by,
                converted_task_id=resolution.converted_task_id,
                create_time=resolution.create_time,
            )
        )
        await self._session.flush()

    async def get_resolution(
        self, resolution_id: uuid.UUID, *, for_update: bool = False
    ) -> Resolution | None:
        statement = select(MeetingResolution).where(
            MeetingResolution.id == resolution_id,
            MeetingResolution.is_delete.is_(False),
        )
        if for_update:
            statement = statement.with_for_update()
        row = (await self._session.execute(statement)).scalar_one_or_none()
        return _resolution_from_row(row) if row is not None else None

    async def save_resolution(self, resolution: Resolution) -> None:
        row = await self._session.get(MeetingResolution, resolution.id)
        if row is None or row.is_delete:
            return
        row.content = resolution.content
        row.owner_id = resolution.owner_id
        row.due_date = resolution.due_date
        row.is_confirmed = resolution.is_confirmed
        row.confirmed_by = resolution.confirmed_by
        row.converted_task_id = resolution.converted_task_id
        await self._session.flush()

    async def list_resolutions(self, meeting_id: uuid.UUID) -> tuple[Resolution, ...]:
        rows = (
            await self._session.execute(
                select(MeetingResolution)
                .where(MeetingResolution.meeting_id == meeting_id)
                .order_by(MeetingResolution.create_time)
            )
        ).scalars()
        return tuple(_resolution_from_row(row) for row in rows)
