"""Request-scoped Meeting Management operations for HTTP and legacy callers."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import date
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.business.meeting_management.application.contracts import (
    AddDiscussionCommand,
    AiSpeakCommand,
    AiVoteCommand,
    CastVoteCommand,
    ConfirmResolutionCommand,
    ConvertResolutionCommand,
    CreateMeetingCommand,
    CreateResolutionCommand,
    DiscussionResult,
    GenerateMinutesCommand,
    GetMeetingQuery,
    ListMeetingsQuery,
    MeetingDetailResult,
    MeetingResult,
    ResolutionResult,
    SetMeetingStatusCommand,
    TallyVotesQuery,
    TaskResult,
    VoteResult,
)
from app.contexts.business.meeting_management.infrastructure.composition import (
    build_meeting_application,
)
from app.contexts.foundations.identity.contracts import Principal, PrincipalType
from app.core.sse import Event
from app.schemas.meeting import DiscussOut

_MISSING_ID = uuid.UUID(int=0)


class PrincipalSource(Protocol):
    """Minimal authenticated-user shape accepted by the HTTP adapter."""

    @property
    def id(self) -> uuid.UUID: ...

    @property
    def role_code(self) -> str: ...

    @property
    def department_id(self) -> uuid.UUID | None: ...

    @property
    def is_active(self) -> bool: ...


def principal_from_user(user: PrincipalSource) -> Principal:
    return Principal(
        principal_type=PrincipalType.USER,
        principal_id=user.id or _MISSING_ID,
        role_code=user.role_code,
        department_id=user.department_id,
        is_active=user.is_active,
    )


async def create_meeting(
    session: AsyncSession,
    *,
    title: str,
    creator_id: uuid.UUID,
    meeting_type: str = "decision",
    participants: list[dict[str, object]] | None = None,
    department_id: uuid.UUID | None = None,
    initial_status: str | None = None,
) -> MeetingResult:
    return await build_meeting_application(session).create(
        CreateMeetingCommand(
            title=title,
            creator_id=creator_id,
            meeting_type=meeting_type,
            participants=tuple(participants or ()),
            department_id=department_id,
            initial_status=initial_status,
        )
    )


async def get_meeting(
    session: AsyncSession,
    meeting_id: uuid.UUID,
    *,
    principal: Principal | None = None,
) -> MeetingResult:
    return await build_meeting_application(session).get(
        GetMeetingQuery(meeting_id=meeting_id, principal=principal)
    )


async def get_meeting_detail(
    session: AsyncSession,
    meeting_id: uuid.UUID,
    *,
    principal: Principal | None = None,
) -> MeetingDetailResult:
    return await build_meeting_application(session).detail(
        GetMeetingQuery(meeting_id=meeting_id, principal=principal)
    )


async def list_meetings(
    session: AsyncSession,
    *,
    status: str | None = None,
    limit: int = 100,
    principal: Principal | None = None,
) -> tuple[MeetingResult, ...]:
    return await build_meeting_application(session).list(
        ListMeetingsQuery(status=status, limit=limit, principal=principal)
    )


async def set_status(
    session: AsyncSession,
    meeting_id: uuid.UUID,
    to_status: str,
) -> MeetingResult:
    return await build_meeting_application(session).set_status(
        SetMeetingStatusCommand(meeting_id=meeting_id, to_status=to_status)
    )


async def add_discussion(
    session: AsyncSession,
    meeting_id: uuid.UUID,
    *,
    speaker_id: uuid.UUID | None,
    speaker_name: str,
    content: str,
) -> DiscussionResult:
    return await build_meeting_application(session).add_discussion(
        AddDiscussionCommand(
            meeting_id=meeting_id,
            speaker_id=speaker_id,
            speaker_name=speaker_name,
            content=content,
        )
    )


async def ai_expert_speak_stream(
    session: AsyncSession,
    meeting_id: uuid.UUID,
    *,
    topic: str,
    operator_id: uuid.UUID | None = None,
) -> AsyncIterator[Event]:
    application = build_meeting_application(session)
    async for event in application.ai_speak_stream(
        AiSpeakCommand(
            meeting_id=meeting_id,
            topic=topic,
            operator_id=operator_id,
        )
    ):
        if event.name == "message_start":
            yield (
                event.name,
                {
                    "speaker_agent_id": str(event.speaker_id),
                    "speaker_name": event.speaker_name,
                },
            )
        elif event.name == "delta":
            yield (event.name, {"text": event.text})
        elif event.discussion is not None:
            yield (
                event.name,
                DiscussOut.model_validate(event.discussion).model_dump(mode="json"),
            )


async def cast_vote(
    session: AsyncSession,
    meeting_id: uuid.UUID,
    *,
    subject: str,
    voter_type: str,
    voter_id: uuid.UUID | None,
    choice: str,
    comment: str | None = None,
) -> VoteResult:
    return await build_meeting_application(session).cast_vote(
        CastVoteCommand(
            meeting_id=meeting_id,
            subject=subject,
            voter_type=voter_type,
            voter_id=voter_id,
            choice=choice,
            comment=comment,
        )
    )


async def ai_expert_vote(
    session: AsyncSession,
    meeting_id: uuid.UUID,
    *,
    subject: str,
    operator_id: uuid.UUID | None = None,
) -> VoteResult:
    return await build_meeting_application(session).ai_vote(
        AiVoteCommand(
            meeting_id=meeting_id,
            subject=subject,
            operator_id=operator_id,
        )
    )


async def tally_votes(
    session: AsyncSession, meeting_id: uuid.UUID, subject: str
) -> dict[str, object]:
    result = await build_meeting_application(session).tally_votes(
        TallyVotesQuery(meeting_id=meeting_id, subject=subject)
    )
    return result.as_dict()


async def list_vote_subjects(
    session: AsyncSession, meeting_id: uuid.UUID
) -> tuple[str, ...]:
    return await build_meeting_application(session).list_vote_subjects(meeting_id)


async def generate_minutes(
    session: AsyncSession,
    meeting_id: uuid.UUID,
    *,
    operator_id: uuid.UUID | None = None,
) -> MeetingResult:
    return await build_meeting_application(session).generate_minutes(
        GenerateMinutesCommand(meeting_id=meeting_id, operator_id=operator_id)
    )


async def create_resolution(
    session: AsyncSession,
    meeting_id: uuid.UUID,
    *,
    content: str,
    owner_id: uuid.UUID | None = None,
    due_date: date | None = None,
) -> ResolutionResult:
    return await build_meeting_application(session).create_resolution(
        CreateResolutionCommand(
            meeting_id=meeting_id,
            content=content,
            owner_id=owner_id,
            due_date=due_date,
        )
    )


async def confirm_resolution(
    session: AsyncSession,
    resolution_id: uuid.UUID,
    *,
    principal: Principal,
) -> ResolutionResult:
    return await build_meeting_application(session).confirm_resolution(
        ConfirmResolutionCommand(
            resolution_id=resolution_id,
            principal=principal,
        )
    )


async def resolution_to_task(
    session: AsyncSession,
    resolution_id: uuid.UUID,
    *,
    creator_id: uuid.UUID,
    assignee_agent_id: uuid.UUID | None = None,
) -> TaskResult:
    return await build_meeting_application(session).convert_resolution(
        ConvertResolutionCommand(
            resolution_id=resolution_id,
            creator_id=creator_id,
            assignee_agent_id=assignee_agent_id,
        )
    )


async def list_discussions(
    session: AsyncSession, meeting_id: uuid.UUID
) -> tuple[DiscussionResult, ...]:
    return await build_meeting_application(session).list_discussions(meeting_id)


async def list_resolutions(
    session: AsyncSession, meeting_id: uuid.UUID
) -> tuple[ResolutionResult, ...]:
    return await build_meeting_application(session).list_resolutions(meeting_id)
