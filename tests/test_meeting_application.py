"""Fast Meeting Management domain/application tests with fake ports."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest

from app.contexts.business.meeting_management.application.contracts import (
    AddDiscussionCommand,
    AiVoteCommand,
    CastVoteCommand,
    ConfirmResolutionCommand,
    ConvertResolutionCommand,
    SetMeetingStatusCommand,
    TallyVotesQuery,
    TaskResult,
)
from app.contexts.business.meeting_management.application.ports import (
    AdvisoryEventKind,
    AdvisoryResult,
    AdvisoryStreamEvent,
    MeetingVisibility,
    MinutesAdvisoryRequest,
    SpeechAdvisoryRequest,
    TaskCreationRequest,
    VoteAdvisoryRequest,
)
from app.contexts.business.meeting_management.application.use_cases import (
    MeetingApplication,
)
from app.contexts.business.meeting_management.domain.models import (
    CLOSED,
    IN_PROGRESS,
    Meeting,
    Resolution,
)
from app.contexts.foundations.identity.contracts import Principal, PrincipalType
from app.contexts.shared_kernel import RuleViolation

NOW = datetime(2026, 7, 23, 9, 0, tzinfo=UTC)


class FakeRepository:
    def __init__(self) -> None:
        self.meeting_rows: dict[uuid.UUID, Meeting] = {}
        self.discussions = []
        self.votes = []
        self.resolution_rows: dict[uuid.UUID, Resolution] = {}

    async def add_meeting(self, meeting: Meeting) -> None:
        self.meeting_rows[meeting.id] = meeting

    async def get_meeting(self, meeting_id: uuid.UUID) -> Meeting | None:
        return self.meeting_rows.get(meeting_id)

    async def save_meeting(self, meeting: Meeting) -> None:
        self.meeting_rows[meeting.id] = meeting

    async def list_meetings(self, *, status: str | None, limit: int, visibility: MeetingVisibility):
        rows = list(self.meeting_rows.values())
        if status:
            rows = [row for row in rows if row.status == status]
        return tuple(rows[:limit])

    async def add_discussion(self, discussion) -> None:
        self.discussions.append(discussion)

    async def list_discussions(self, meeting_id: uuid.UUID):
        return tuple(row for row in self.discussions if row.meeting_id == meeting_id)

    async def add_vote(self, vote) -> None:
        self.votes.append(vote)

    async def list_votes(self, meeting_id: uuid.UUID, subject: str):
        return tuple(
            row for row in self.votes if row.meeting_id == meeting_id and row.subject == subject
        )

    async def list_vote_subjects(self, meeting_id: uuid.UUID):
        return tuple(
            sorted({row.subject for row in self.votes if row.meeting_id == meeting_id})
        )

    async def add_resolution(self, resolution: Resolution) -> None:
        self.resolution_rows[resolution.id] = resolution

    async def get_resolution(
        self, resolution_id: uuid.UUID, *, for_update: bool = False
    ) -> Resolution | None:
        return self.resolution_rows.get(resolution_id)

    async def save_resolution(self, resolution: Resolution) -> None:
        self.resolution_rows[resolution.id] = resolution

    async def list_resolutions(self, meeting_id: uuid.UUID):
        return tuple(row for row in self.resolution_rows.values() if row.meeting_id == meeting_id)


class FakeUnitOfWork:
    def __init__(self, state: FakeState) -> None:
        self.meetings = state.repository
        self._state = state

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        if exc_type is not None:
            await self.rollback()

    async def commit(self) -> None:
        self._state.commits += 1

    async def rollback(self) -> None:
        self._state.rollbacks += 1


class FakeState:
    def __init__(self) -> None:
        self.repository = FakeRepository()
        self.commits = 0
        self.rollbacks = 0

    def uow(self) -> FakeUnitOfWork:
        return FakeUnitOfWork(self)


class FakeAdvisory:
    async def speak(self, request: SpeechAdvisoryRequest) -> AsyncIterator[AdvisoryStreamEvent]:
        if False:
            yield AdvisoryStreamEvent(  # pragma: no cover
                kind=AdvisoryEventKind.DELTA,
                expert_id=uuid.UUID(int=900),
                expert_name="会商AI专家",
            )

    async def vote(self, request: VoteAdvisoryRequest) -> AdvisoryResult:
        return AdvisoryResult(
            expert_id=uuid.UUID(int=900),
            expert_name="会商AI专家",
            content="approve\nAI 建议通过",
            comment="approve\nAI 建议通过",
        )

    async def minutes(self, request: MinutesAdvisoryRequest) -> AdvisoryResult:
        return AdvisoryResult(
            expert_id=uuid.UUID(int=900),
            expert_name="会商AI专家",
            content="AI 建议纪要",
        )


class FakeTasks:
    def __init__(self) -> None:
        self.requests: list[TaskCreationRequest] = []
        self.fail = False

    async def create_task(self, request: TaskCreationRequest) -> TaskResult:
        self.requests.append(request)
        if self.fail:
            raise RuntimeError("task failed")
        return TaskResult(
            id=uuid.UUID(int=700),
            title=request.title,
            task_type=request.task_type,
            priority="normal",
            status="created",
            creator_id=request.creator_id,
            assignee_agent_id=request.assignee_agent_id,
            parent_id=None,
            sla_hours=None,
            result_content=None,
            create_time=NOW,
        )


class AllowAllVisibility:
    def visibility_for(self, principal: Principal | None) -> MeetingVisibility:
        return MeetingVisibility(unrestricted=True)

    def ensure_visible(self, principal: Principal | None, meeting: Meeting) -> None:
        return None


class FixedClock:
    def now(self) -> datetime:
        return NOW


class SequenceIdentifiers:
    def __init__(self) -> None:
        self.value = 1000

    def new_id(self) -> uuid.UUID:
        self.value += 1
        return uuid.UUID(int=self.value)


def build_application(state: FakeState, tasks: FakeTasks | None = None) -> MeetingApplication:
    return MeetingApplication(
        uow_factory=state.uow,
        advisory_port=FakeAdvisory(),
        task_port=tasks or FakeTasks(),
        visibility_policy=AllowAllVisibility(),
        clock=FixedClock(),
        identifiers=SequenceIdentifiers(),
    )


def seed_meeting(state: FakeState) -> Meeting:
    meeting = Meeting(
        id=uuid.UUID(int=1),
        title="决策会",
        meeting_type="decision",
        status=IN_PROGRESS,
        creator_id=uuid.UUID(int=2),
        create_time=NOW,
    )
    state.repository.meeting_rows[meeting.id] = meeting
    return meeting


async def test_ai_vote_is_advisory_and_cannot_make_human_vote_pass() -> None:
    state = FakeState()
    meeting = seed_meeting(state)
    application = build_application(state)

    await application.cast_vote(
        CastVoteCommand(
            meeting_id=meeting.id,
            subject="方案A",
            voter_type="human",
            voter_id=uuid.UUID(int=3),
            choice="reject",
        )
    )
    ai_vote = await application.ai_vote(AiVoteCommand(meeting_id=meeting.id, subject="方案A"))
    tally = await application.tally_votes(TallyVotesQuery(meeting_id=meeting.id, subject="方案A"))

    assert ai_vote.voter_type == "ai" and ai_vote.choice == "approve"
    assert tally.ai == {"approve": 1}
    assert tally.human == {"reject": 1}
    assert tally.human_passed is False


async def test_only_human_principal_can_confirm_resolution() -> None:
    state = FakeState()
    meeting = seed_meeting(state)
    resolution = Resolution(
        id=uuid.UUID(int=4),
        meeting_id=meeting.id,
        content="执行方案A",
        owner_id=None,
        due_date=None,
        is_confirmed=False,
        confirmed_by=None,
        converted_task_id=None,
        create_time=NOW,
    )
    state.repository.resolution_rows[resolution.id] = resolution
    application = build_application(state)

    with pytest.raises(RuleViolation, match="只能由真人确认"):
        await application.confirm_resolution(
            ConfirmResolutionCommand(
                resolution_id=resolution.id,
                principal=Principal(
                    principal_type=PrincipalType.AGENT,
                    principal_id=uuid.UUID(int=5),
                    role_code="agent",
                    department_id=None,
                ),
            )
        )

    assert resolution.is_confirmed is False
    assert state.commits == 0
    assert state.rollbacks == 1


async def test_resolution_conversion_is_at_most_once() -> None:
    state = FakeState()
    meeting = seed_meeting(state)
    resolution = Resolution(
        id=uuid.UUID(int=6),
        meeting_id=meeting.id,
        content="执行方案A",
        owner_id=None,
        due_date=None,
        is_confirmed=True,
        confirmed_by=uuid.UUID(int=2),
        converted_task_id=None,
        create_time=NOW,
    )
    state.repository.resolution_rows[resolution.id] = resolution
    tasks = FakeTasks()
    application = build_application(state, tasks)
    command = ConvertResolutionCommand(
        resolution_id=resolution.id,
        creator_id=uuid.UUID(int=2),
    )

    task = await application.convert_resolution(command)
    with pytest.raises(RuleViolation, match="已转过"):
        await application.convert_resolution(command)

    assert task.id == resolution.converted_task_id
    assert len(tasks.requests) == 1


async def test_task_failure_rolls_back_without_conversion_marker() -> None:
    state = FakeState()
    meeting = seed_meeting(state)
    resolution = Resolution(
        id=uuid.UUID(int=7),
        meeting_id=meeting.id,
        content="执行方案B",
        owner_id=None,
        due_date=None,
        is_confirmed=True,
        confirmed_by=uuid.UUID(int=2),
        converted_task_id=None,
        create_time=NOW,
    )
    state.repository.resolution_rows[resolution.id] = resolution
    tasks = FakeTasks()
    tasks.fail = True
    application = build_application(state, tasks)

    with pytest.raises(RuntimeError, match="task failed"):
        await application.convert_resolution(
            ConvertResolutionCommand(
                resolution_id=resolution.id,
                creator_id=uuid.UUID(int=2),
            )
        )

    assert resolution.converted_task_id is None
    assert state.commits == 0
    assert state.rollbacks == 1


# ── 闭会自动纪要（docs/26 A3：内部分析辅助·无红线停点·无发言静默跳过）─────────
async def test_closing_meeting_auto_generates_minutes() -> None:
    state = FakeState()
    meeting = seed_meeting(state)
    application = build_application(state)
    await application.add_discussion(
        AddDiscussionCommand(
            meeting_id=meeting.id,
            speaker_id=uuid.UUID(int=2),
            speaker_name="系统",
            content="紧急会商议题：舆情",
        )
    )

    await application.set_status(SetMeetingStatusCommand(meeting_id=meeting.id, to_status=CLOSED))

    # 闭会即自动生成纪要（FakeAdvisory.minutes 回吐并 record 到 meeting.summary）
    assert state.repository.meeting_rows[meeting.id].summary == "AI 建议纪要"


async def test_closing_meeting_without_discussion_skips_minutes_silently() -> None:
    state = FakeState()
    meeting = seed_meeting(state)
    application = build_application(state)

    # 无发言 → generate_minutes 抛 RuleViolation，被 set_status 静默吞掉，闭会仍成功返回
    result = await application.set_status(
        SetMeetingStatusCommand(meeting_id=meeting.id, to_status=CLOSED)
    )

    assert result.status == CLOSED
    assert state.repository.meeting_rows[meeting.id].summary is None
