"""Meeting Management use cases and transaction ownership."""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from copy import deepcopy

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
    MeetingStreamEvent,
    ResolutionResult,
    SetMeetingStatusCommand,
    TallyVotesQuery,
    TaskResult,
    VoteResult,
    VoteTallyResult,
)
from app.contexts.business.meeting_management.application.ports import (
    AdvisoryEventKind,
    Clock,
    IdentifierPort,
    MeetingAdvisoryPort,
    MeetingRepository,
    MeetingUnitOfWorkFactory,
    MeetingVisibilityPolicy,
    MinutesAdvisoryRequest,
    SpeechAdvisoryRequest,
    TaskCreationPort,
    TaskCreationRequest,
    VoteAdvisoryRequest,
)
from app.contexts.business.meeting_management.domain.models import (
    CLOSED,
    SCHEDULED,
    ConfirmationActorType,
    Discussion,
    Meeting,
    Resolution,
    Vote,
    parse_vote_choice,
)
from app.contexts.foundations.identity.contracts import PrincipalType
from app.contexts.shared_kernel import ResourceNotFound, RuleViolation

logger = logging.getLogger(__name__)


def _meeting_result(meeting: Meeting) -> MeetingResult:
    assert meeting.create_time is not None
    return MeetingResult(
        id=meeting.id,
        title=meeting.title,
        meeting_type=meeting.meeting_type,
        status=meeting.status,
        scheduled_at=meeting.scheduled_at,
        creator_id=meeting.creator_id,
        participants=deepcopy(meeting.participants),
        department_id=meeting.department_id,
        summary=meeting.summary,
        create_time=meeting.create_time,
    )


def _discussion_result(discussion: Discussion) -> DiscussionResult:
    return DiscussionResult(
        id=discussion.id,
        speaker_type=discussion.speaker_type,
        speaker_name=discussion.speaker_name,
        content=discussion.content,
        create_time=discussion.create_time,
    )


def _vote_result(vote: Vote) -> VoteResult:
    return VoteResult(
        id=vote.id,
        subject=vote.subject,
        voter_type=vote.voter_type,
        choice=vote.choice,
        comment=vote.comment,
        create_time=vote.create_time,
    )


def _resolution_result(resolution: Resolution) -> ResolutionResult:
    return ResolutionResult(
        id=resolution.id,
        content=resolution.content,
        owner_id=resolution.owner_id,
        due_date=resolution.due_date,
        is_confirmed=resolution.is_confirmed,
        confirmed_by=resolution.confirmed_by,
        converted_task_id=resolution.converted_task_id,
        create_time=resolution.create_time,
    )


class MeetingApplication:
    """Single application boundary for Meeting-owned behavior."""

    def __init__(
        self,
        *,
        uow_factory: MeetingUnitOfWorkFactory,
        advisory_port: MeetingAdvisoryPort,
        task_port: TaskCreationPort,
        visibility_policy: MeetingVisibilityPolicy,
        clock: Clock,
        identifiers: IdentifierPort,
    ) -> None:
        self._uow_factory = uow_factory
        self._advisory = advisory_port
        self._tasks = task_port
        self._visibility = visibility_policy
        self._clock = clock
        self._identifiers = identifiers

    async def create(self, command: CreateMeetingCommand) -> MeetingResult:
        meeting = Meeting(
            id=self._identifiers.new_id(),
            title=command.title,
            meeting_type=command.meeting_type,
            status=command.initial_status or SCHEDULED,
            creator_id=command.creator_id,
            participants=[deepcopy(item) for item in command.participants],
            department_id=command.department_id,
            create_time=self._clock.now(),
        )
        async with self._uow_factory() as uow:
            await uow.meetings.add_meeting(meeting)
            await uow.commit()
        return _meeting_result(meeting)

    async def get(self, query: GetMeetingQuery) -> MeetingResult:
        async with self._uow_factory() as uow:
            meeting = await self._meeting_required(uow.meetings, query.meeting_id)
            self._visibility.ensure_visible(query.principal, meeting)
        return _meeting_result(meeting)

    async def detail(self, query: GetMeetingQuery) -> MeetingDetailResult:
        async with self._uow_factory() as uow:
            meeting = await self._meeting_required(uow.meetings, query.meeting_id)
            self._visibility.ensure_visible(query.principal, meeting)
            discussions = await uow.meetings.list_discussions(meeting.id)
            resolutions = await uow.meetings.list_resolutions(meeting.id)
        return MeetingDetailResult(
            meeting=_meeting_result(meeting),
            discussions=tuple(_discussion_result(item) for item in discussions),
            resolutions=tuple(_resolution_result(item) for item in resolutions),
        )

    async def list(self, query: ListMeetingsQuery) -> tuple[MeetingResult, ...]:
        async with self._uow_factory() as uow:
            meetings = await uow.meetings.list_meetings(
                status=query.status,
                limit=query.limit,
                visibility=self._visibility.visibility_for(query.principal),
            )
        return tuple(_meeting_result(item) for item in meetings)

    async def set_status(self, command: SetMeetingStatusCommand) -> MeetingResult:
        async with self._uow_factory() as uow:
            meeting = await self._meeting_required(uow.meetings, command.meeting_id)
            meeting.transition_to(command.to_status)
            await uow.meetings.save_meeting(meeting)
            await uow.commit()
        if command.to_status == CLOSED:
            # 会议闭会自动生成纪要（A3，内部分析辅助·可编辑·无红线停点）；无发言时
            # generate_minutes 会 raise RuleViolation，此处静默跳过而非打断闭会响应。
            try:
                await self.generate_minutes(GenerateMinutesCommand(meeting_id=meeting.id))
            except RuleViolation:
                logger.info("会议 %s 闭会时无发言，跳过自动纪要", meeting.id)
        return _meeting_result(meeting)

    async def add_discussion(self, command: AddDiscussionCommand) -> DiscussionResult:
        async with self._uow_factory() as uow:
            meeting = await self._meeting_required(uow.meetings, command.meeting_id)
            meeting.require_in_progress()
            discussion = Discussion(
                id=self._identifiers.new_id(),
                meeting_id=meeting.id,
                speaker_type="human",
                speaker_id=command.speaker_id,
                speaker_name=command.speaker_name,
                content=command.content,
                create_time=self._clock.now(),
            )
            await uow.meetings.add_discussion(discussion)
            await uow.commit()
        return _discussion_result(discussion)

    async def ai_speak_stream(self, command: AiSpeakCommand) -> AsyncIterator[MeetingStreamEvent]:
        async with self._uow_factory() as uow:
            meeting = await self._meeting_required(uow.meetings, command.meeting_id)
            meeting.require_in_progress()
            history = await uow.meetings.list_discussions(meeting.id)

        request = SpeechAdvisoryRequest(
            topic=command.topic,
            history=tuple((item.speaker_name, item.content) for item in history),
            operator_id=command.operator_id,
        )
        async for event in self._advisory.speak(request):
            if event.kind is AdvisoryEventKind.STARTED:
                yield MeetingStreamEvent(
                    name="message_start",
                    speaker_id=event.expert_id,
                    speaker_name=event.expert_name,
                )
                continue
            if event.kind is AdvisoryEventKind.DELTA:
                yield MeetingStreamEvent(name="delta", text=event.text)
                continue
            discussion = Discussion(
                id=self._identifiers.new_id(),
                meeting_id=meeting.id,
                speaker_type="ai",
                speaker_id=event.expert_id,
                speaker_name=event.expert_name,
                content=event.text,
                create_time=self._clock.now(),
            )
            async with self._uow_factory() as uow:
                await uow.meetings.add_discussion(discussion)
                await uow.commit()
            yield MeetingStreamEvent(
                name="message_end",
                discussion=_discussion_result(discussion),
            )

    async def cast_vote(self, command: CastVoteCommand) -> VoteResult:
        vote = Vote.create(
            vote_id=self._identifiers.new_id(),
            meeting_id=command.meeting_id,
            subject=command.subject,
            voter_type=command.voter_type,
            voter_id=command.voter_id,
            choice=command.choice,
            comment=command.comment,
            create_time=self._clock.now(),
        )
        async with self._uow_factory() as uow:
            meeting = await self._meeting_required(uow.meetings, command.meeting_id)
            meeting.require_in_progress()
            await uow.meetings.add_vote(vote)
            await uow.commit()
        return _vote_result(vote)

    async def ai_vote(self, command: AiVoteCommand) -> VoteResult:
        async with self._uow_factory() as uow:
            meeting = await self._meeting_required(uow.meetings, command.meeting_id)
            meeting.require_in_progress()
        advisory = await self._advisory.vote(
            VoteAdvisoryRequest(
                subject=command.subject,
                operator_id=command.operator_id,
            )
        )
        vote = Vote.create(
            vote_id=self._identifiers.new_id(),
            meeting_id=meeting.id,
            subject=command.subject,
            voter_type="ai",
            voter_id=advisory.expert_id,
            choice=parse_vote_choice(advisory.content),
            comment=advisory.comment,
            create_time=self._clock.now(),
        )
        async with self._uow_factory() as uow:
            await uow.meetings.add_vote(vote)
            await uow.commit()
        return _vote_result(vote)

    async def tally_votes(self, query: TallyVotesQuery) -> VoteTallyResult:
        async with self._uow_factory() as uow:
            votes = await uow.meetings.list_votes(query.meeting_id, query.subject)
        tally: dict[str, dict[str, int]] = {"human": {}, "ai": {}}
        for vote in votes:
            bucket = tally.setdefault(vote.voter_type, {})
            bucket[vote.choice] = bucket.get(vote.choice, 0) + 1
        human = tally.get("human", {})
        return VoteTallyResult(
            subject=query.subject,
            human=human,
            ai=tally.get("ai", {}),
            human_passed=human.get("approve", 0) > human.get("reject", 0),
        )

    async def generate_minutes(self, command: GenerateMinutesCommand) -> MeetingResult:
        async with self._uow_factory() as uow:
            meeting = await self._meeting_required(uow.meetings, command.meeting_id)
            discussions = await uow.meetings.list_discussions(meeting.id)
        if not discussions:
            raise RuleViolation("会议暂无发言，无法生成纪要")
        advisory = await self._advisory.minutes(
            MinutesAdvisoryRequest(
                title=meeting.title,
                discussions=tuple(
                    (item.speaker_name, item.speaker_type, item.content) for item in discussions
                ),
                operator_id=command.operator_id,
            )
        )
        meeting.record_minutes(advisory.content)
        async with self._uow_factory() as uow:
            await uow.meetings.save_meeting(meeting)
            await uow.commit()
        return _meeting_result(meeting)

    async def create_resolution(self, command: CreateResolutionCommand) -> ResolutionResult:
        async with self._uow_factory() as uow:
            await self._meeting_required(uow.meetings, command.meeting_id)
            resolution = Resolution(
                id=self._identifiers.new_id(),
                meeting_id=command.meeting_id,
                content=command.content,
                owner_id=command.owner_id,
                due_date=command.due_date,
                is_confirmed=False,
                confirmed_by=None,
                converted_task_id=None,
                create_time=self._clock.now(),
            )
            await uow.meetings.add_resolution(resolution)
            await uow.commit()
        return _resolution_result(resolution)

    async def confirm_resolution(self, command: ConfirmResolutionCommand) -> ResolutionResult:
        actor_type = (
            ConfirmationActorType.HUMAN
            if command.principal.principal_type is PrincipalType.USER
            else ConfirmationActorType.AI
        )
        async with self._uow_factory() as uow:
            resolution = await self._resolution_required(uow.meetings, command.resolution_id)
            resolution.confirm(
                actor_id=command.principal.principal_id,
                actor_type=actor_type,
            )
            await uow.meetings.save_resolution(resolution)
            await uow.commit()
        return _resolution_result(resolution)

    async def convert_resolution(self, command: ConvertResolutionCommand) -> TaskResult:
        async with self._uow_factory() as uow:
            resolution = await self._resolution_required(
                uow.meetings,
                command.resolution_id,
                for_update=True,
            )
            resolution.assert_convertible()
            task = await self._tasks.create_task(
                TaskCreationRequest(
                    title=f"[会议决议] {resolution.content[:60]}",
                    task_type="resolution_execution",
                    creator_id=command.creator_id,
                    assignee_agent_id=command.assignee_agent_id,
                    payload=(("resolution_id", str(resolution.id)),),
                )
            )
            resolution.record_conversion(task.id)
            await uow.meetings.save_resolution(resolution)
            await uow.commit()
        return task

    async def list_vote_subjects(self, meeting_id: uuid.UUID) -> tuple[str, ...]:
        async with self._uow_factory() as uow:
            return await uow.meetings.list_vote_subjects(meeting_id)

    async def list_discussions(self, meeting_id: uuid.UUID) -> tuple[DiscussionResult, ...]:
        async with self._uow_factory() as uow:
            discussions = await uow.meetings.list_discussions(meeting_id)
        return tuple(_discussion_result(item) for item in discussions)

    async def list_resolutions(self, meeting_id: uuid.UUID) -> tuple[ResolutionResult, ...]:
        async with self._uow_factory() as uow:
            resolutions = await uow.meetings.list_resolutions(meeting_id)
        return tuple(_resolution_result(item) for item in resolutions)

    @staticmethod
    async def _meeting_required(repository: MeetingRepository, meeting_id: uuid.UUID) -> Meeting:
        meeting = await repository.get_meeting(meeting_id)
        if meeting is None:
            raise ResourceNotFound("会议不存在")
        return meeting

    @staticmethod
    async def _resolution_required(
        repository: MeetingRepository,
        resolution_id: uuid.UUID,
        *,
        for_update: bool = False,
    ) -> Resolution:
        resolution = await repository.get_resolution(resolution_id, for_update=for_update)
        if resolution is None:
            raise ResourceNotFound("决议不存在")
        return resolution
