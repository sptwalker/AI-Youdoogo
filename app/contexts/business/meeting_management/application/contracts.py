"""Plain Meeting Management commands, queries, results, and stream events."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime

from app.contexts.foundations.identity.contracts import Principal


@dataclass(frozen=True, slots=True)
class CreateMeetingCommand:
    title: str
    creator_id: uuid.UUID
    meeting_type: str = "decision"
    participants: tuple[dict[str, object], ...] = ()
    department_id: uuid.UUID | None = None
    # 建会即直接进 IN_PROGRESS（跳过显式 set_status 流转）；调用方自行决定，默认沿用
    # 既有行为（SCHEDULED）。convene_consultation 建紧急会商时传 IN_PROGRESS，避免
    # 引入对 set_status 的额外跨 Context 调用。
    initial_status: str | None = None


@dataclass(frozen=True, slots=True)
class GetMeetingQuery:
    meeting_id: uuid.UUID
    principal: Principal | None = None


@dataclass(frozen=True, slots=True)
class ListMeetingsQuery:
    status: str | None = None
    limit: int = 100
    principal: Principal | None = None


@dataclass(frozen=True, slots=True)
class SetMeetingStatusCommand:
    meeting_id: uuid.UUID
    to_status: str


@dataclass(frozen=True, slots=True)
class AddDiscussionCommand:
    meeting_id: uuid.UUID
    speaker_id: uuid.UUID | None
    speaker_name: str
    content: str


@dataclass(frozen=True, slots=True)
class AiSpeakCommand:
    meeting_id: uuid.UUID
    topic: str
    operator_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class CastVoteCommand:
    meeting_id: uuid.UUID
    subject: str
    voter_type: str
    voter_id: uuid.UUID | None
    choice: str
    comment: str | None = None


@dataclass(frozen=True, slots=True)
class AiVoteCommand:
    meeting_id: uuid.UUID
    subject: str
    operator_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class TallyVotesQuery:
    meeting_id: uuid.UUID
    subject: str


@dataclass(frozen=True, slots=True)
class GenerateMinutesCommand:
    meeting_id: uuid.UUID
    operator_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class CreateResolutionCommand:
    meeting_id: uuid.UUID
    content: str
    owner_id: uuid.UUID | None = None
    due_date: date | None = None


@dataclass(frozen=True, slots=True)
class ConfirmResolutionCommand:
    resolution_id: uuid.UUID
    principal: Principal


@dataclass(frozen=True, slots=True)
class ConvertResolutionCommand:
    resolution_id: uuid.UUID
    creator_id: uuid.UUID
    assignee_agent_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class MeetingResult:
    id: uuid.UUID
    title: str
    meeting_type: str
    status: str
    scheduled_at: datetime | None
    creator_id: uuid.UUID
    participants: list[dict[str, object]]
    department_id: uuid.UUID | None
    summary: str | None
    create_time: datetime


@dataclass(frozen=True, slots=True)
class DiscussionResult:
    id: uuid.UUID
    speaker_type: str
    speaker_name: str
    content: str
    create_time: datetime


@dataclass(frozen=True, slots=True)
class VoteResult:
    id: uuid.UUID
    subject: str
    voter_type: str
    choice: str
    comment: str | None
    create_time: datetime


@dataclass(frozen=True, slots=True)
class ResolutionResult:
    id: uuid.UUID
    content: str
    owner_id: uuid.UUID | None
    due_date: date | None
    is_confirmed: bool
    confirmed_by: uuid.UUID | None
    converted_task_id: uuid.UUID | None
    create_time: datetime


@dataclass(frozen=True, slots=True)
class MeetingDetailResult:
    meeting: MeetingResult
    discussions: tuple[DiscussionResult, ...]
    resolutions: tuple[ResolutionResult, ...]


@dataclass(frozen=True, slots=True)
class VoteTallyResult:
    subject: str
    human: dict[str, int]
    ai: dict[str, int]
    human_passed: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "subject": self.subject,
            "human": dict(self.human),
            "ai": dict(self.ai),
            "human_passed": self.human_passed,
        }


@dataclass(frozen=True, slots=True)
class TaskResult:
    id: uuid.UUID
    title: str
    task_type: str
    priority: str
    status: str
    creator_id: uuid.UUID
    assignee_agent_id: uuid.UUID | None
    parent_id: uuid.UUID | None
    sla_hours: int | None
    result_content: str | None
    create_time: datetime


@dataclass(frozen=True, slots=True)
class MeetingStreamEvent:
    name: str
    speaker_id: uuid.UUID | None = None
    speaker_name: str = ""
    text: str = ""
    discussion: DiscussionResult | None = None
