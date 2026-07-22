"""Meeting CRUD, human decisions, and compatibility AI action facade."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import date
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from app.models.system import SysUser

from app.contexts.shared_kernel import ResourceNotFound, RuleViolation
from app.core.sse import Event
from app.models.meeting import (
    CLOSED,
    IN_PROGRESS,
    SCHEDULED,
    MeetingDiscuss,
    MeetingInfo,
    MeetingResolution,
    MeetingVote,
)
from app.models.task import TaskCard
from app.services import meeting_ai_actions

EXPERT_NAME = meeting_ai_actions.EXPERT_NAME
_VALID_CHOICES = meeting_ai_actions.VALID_CHOICES
_MEETING_TRANSITIONS: dict[str, frozenset[str]] = {
    SCHEDULED: frozenset({IN_PROGRESS, CLOSED}),
    IN_PROGRESS: frozenset({CLOSED}),
    CLOSED: frozenset(),
}


async def get_meeting(db: AsyncSession, meeting_id: uuid.UUID) -> MeetingInfo:
    meeting = await db.get(MeetingInfo, meeting_id)
    if meeting is None or meeting.is_delete:
        raise ResourceNotFound("会议不存在")
    return meeting


async def create_meeting(
    db: AsyncSession,
    *,
    title: str,
    creator_id: uuid.UUID,
    meeting_type: str = "decision",
    participants: list[dict[str, Any]] | None = None,
    department_id: uuid.UUID | None = None,
) -> MeetingInfo:
    meeting = MeetingInfo(
        title=title,
        creator_id=creator_id,
        meeting_type=meeting_type,
        participants=participants or [],
        department_id=department_id,
    )
    db.add(meeting)
    await db.commit()
    await db.refresh(meeting)
    return meeting


async def set_status(
    db: AsyncSession, meeting_id: uuid.UUID, to_status: str
) -> MeetingInfo:
    meeting = await get_meeting(db, meeting_id)
    if to_status not in _MEETING_TRANSITIONS.get(meeting.status, frozenset()):
        raise RuleViolation(f"非法会议状态流转：{meeting.status} → {to_status}")
    meeting.status = to_status
    await db.commit()
    await db.refresh(meeting)
    return meeting


def _require_in_progress(meeting: MeetingInfo) -> None:
    if meeting.status != IN_PROGRESS:
        raise RuleViolation(f"会议当前状态 {meeting.status}，需先开始（in_progress）")


async def add_discussion(
    db: AsyncSession,
    meeting_id: uuid.UUID,
    *,
    speaker_id: uuid.UUID | None,
    speaker_name: str,
    content: str,
) -> MeetingDiscuss:
    meeting = await get_meeting(db, meeting_id)
    _require_in_progress(meeting)
    discussion = MeetingDiscuss(
        meeting_id=meeting_id,
        speaker_type="human",
        speaker_id=speaker_id,
        speaker_name=speaker_name,
        content=content,
    )
    db.add(discussion)
    await db.commit()
    await db.refresh(discussion)
    return discussion


async def ai_expert_speak_stream(
    db: AsyncSession,
    meeting_id: uuid.UUID,
    *,
    topic: str,
    operator_id: uuid.UUID | None = None,
) -> AsyncIterator[Event]:
    async for event in meeting_ai_actions.ai_expert_speak_stream(
        db, meeting_id, topic=topic, operator_id=operator_id
    ):
        yield event


async def cast_vote(
    db: AsyncSession,
    meeting_id: uuid.UUID,
    *,
    subject: str,
    voter_type: str,
    voter_id: uuid.UUID | None,
    choice: str,
    comment: str | None = None,
) -> MeetingVote:
    if choice not in _VALID_CHOICES:
        raise RuleViolation(f"choice 仅支持 {'/'.join(_VALID_CHOICES)}")
    if voter_type not in ("human", "ai"):
        raise RuleViolation("voter_type 仅支持 human/ai")
    meeting = await get_meeting(db, meeting_id)
    _require_in_progress(meeting)
    vote = MeetingVote(
        meeting_id=meeting_id,
        subject=subject,
        voter_type=voter_type,
        voter_id=voter_id,
        choice=choice,
        comment=comment,
    )
    db.add(vote)
    await db.commit()
    await db.refresh(vote)
    return vote


_parse_choice = meeting_ai_actions.parse_choice


async def ai_expert_vote(
    db: AsyncSession,
    meeting_id: uuid.UUID,
    *,
    subject: str,
    operator_id: uuid.UUID | None = None,
) -> MeetingVote:
    return await meeting_ai_actions.ai_expert_vote(
        db, meeting_id, subject=subject, operator_id=operator_id
    )


async def tally_votes(
    db: AsyncSession, meeting_id: uuid.UUID, subject: str
) -> dict[str, Any]:
    stmt = (
        select(MeetingVote.voter_type, MeetingVote.choice, func.count())
        .where(MeetingVote.meeting_id == meeting_id, MeetingVote.subject == subject)
        .group_by(MeetingVote.voter_type, MeetingVote.choice)
    )
    rows = (await db.execute(stmt)).all()
    tally: dict[str, dict[str, int]] = {"human": {}, "ai": {}}
    for voter_type, choice, count in rows:
        tally.setdefault(voter_type, {})[choice] = int(count)
    human = tally.get("human", {})
    return {
        "subject": subject,
        "human": human,
        "ai": tally.get("ai", {}),
        "human_passed": human.get("approve", 0) > human.get("reject", 0),
    }


async def generate_minutes(
    db: AsyncSession,
    meeting_id: uuid.UUID,
    *,
    operator_id: uuid.UUID | None = None,
) -> MeetingInfo:
    return await meeting_ai_actions.generate_minutes(
        db, meeting_id, operator_id=operator_id
    )


async def create_resolution(
    db: AsyncSession,
    meeting_id: uuid.UUID,
    *,
    content: str,
    owner_id: uuid.UUID | None = None,
    due_date: date | None = None,
) -> MeetingResolution:
    await get_meeting(db, meeting_id)
    resolution = MeetingResolution(
        meeting_id=meeting_id,
        content=content,
        owner_id=owner_id,
        due_date=due_date,
    )
    db.add(resolution)
    await db.commit()
    await db.refresh(resolution)
    return resolution


async def confirm_resolution(
    db: AsyncSession, resolution_id: uuid.UUID, *, confirmed_by: uuid.UUID
) -> MeetingResolution:
    resolution = await db.get(MeetingResolution, resolution_id)
    if resolution is None or resolution.is_delete:
        raise ResourceNotFound("决议不存在")
    resolution.is_confirmed = True
    resolution.confirmed_by = confirmed_by
    await db.commit()
    await db.refresh(resolution)
    return resolution


async def resolution_to_task(
    db: AsyncSession,
    resolution_id: uuid.UUID,
    *,
    creator_id: uuid.UUID,
    assignee_agent_id: uuid.UUID | None = None,
) -> TaskCard:
    return await meeting_ai_actions.resolution_to_task(
        db,
        resolution_id,
        creator_id=creator_id,
        assignee_agent_id=assignee_agent_id,
    )


async def list_discussions(
    db: AsyncSession, meeting_id: uuid.UUID
) -> list[MeetingDiscuss]:
    stmt = (
        select(MeetingDiscuss)
        .where(MeetingDiscuss.meeting_id == meeting_id)
        .order_by(MeetingDiscuss.create_time)
    )
    return list((await db.execute(stmt)).scalars())


async def list_resolutions(
    db: AsyncSession, meeting_id: uuid.UUID
) -> list[MeetingResolution]:
    stmt = (
        select(MeetingResolution)
        .where(MeetingResolution.meeting_id == meeting_id)
        .order_by(MeetingResolution.create_time)
    )
    return list((await db.execute(stmt)).scalars())


async def list_meetings(
    db: AsyncSession,
    *,
    status: str | None = None,
    limit: int = 100,
    viewer: SysUser | None = None,
) -> list[MeetingInfo]:
    stmt = select(MeetingInfo).where(MeetingInfo.is_delete.is_(False))
    if status:
        stmt = stmt.where(MeetingInfo.status == status)
    if viewer is not None:
        from app.services import permission_service

        condition = permission_service.row_filter(MeetingInfo, viewer)
        if condition is not None:
            stmt = stmt.where(condition)
    return list(
        (
            await db.execute(
                stmt.order_by(MeetingInfo.create_time.desc()).limit(limit)
            )
        ).scalars()
    )
