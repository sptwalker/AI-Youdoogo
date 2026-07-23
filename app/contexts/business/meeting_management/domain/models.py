"""Framework-independent Meeting Management state and invariants."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum

from app.contexts.shared_kernel import RuleViolation

SCHEDULED = "scheduled"
IN_PROGRESS = "in_progress"
CLOSED = "closed"

VALID_VOTE_CHOICES = ("approve", "reject", "abstain")
VALID_VOTER_TYPES = ("human", "ai")

_MEETING_TRANSITIONS: dict[str, frozenset[str]] = {
    SCHEDULED: frozenset({IN_PROGRESS, CLOSED}),
    IN_PROGRESS: frozenset({CLOSED}),
    CLOSED: frozenset(),
}


class ConfirmationActorType(StrEnum):
    HUMAN = "human"
    AI = "ai"


@dataclass(slots=True)
class Meeting:
    id: uuid.UUID
    title: str
    meeting_type: str
    status: str
    creator_id: uuid.UUID
    participants: list[dict[str, object]] = field(default_factory=list)
    department_id: uuid.UUID | None = None
    scheduled_at: datetime | None = None
    summary: str | None = None
    create_time: datetime | None = None

    def transition_to(self, to_status: str) -> None:
        if to_status not in _MEETING_TRANSITIONS.get(self.status, frozenset()):
            raise RuleViolation(f"非法会议状态流转：{self.status} → {to_status}")
        self.status = to_status

    def require_in_progress(self) -> None:
        if self.status != IN_PROGRESS:
            raise RuleViolation(f"会议当前状态 {self.status}，需先开始（in_progress）")

    def record_minutes(self, summary: str) -> None:
        self.summary = summary


@dataclass(frozen=True, slots=True)
class Discussion:
    id: uuid.UUID
    meeting_id: uuid.UUID
    speaker_type: str
    speaker_id: uuid.UUID | None
    speaker_name: str
    content: str
    create_time: datetime


@dataclass(frozen=True, slots=True)
class Vote:
    id: uuid.UUID
    meeting_id: uuid.UUID
    subject: str
    voter_type: str
    voter_id: uuid.UUID | None
    choice: str
    comment: str | None
    create_time: datetime

    @classmethod
    def create(
        cls,
        *,
        vote_id: uuid.UUID,
        meeting_id: uuid.UUID,
        subject: str,
        voter_type: str,
        voter_id: uuid.UUID | None,
        choice: str,
        comment: str | None,
        create_time: datetime,
    ) -> Vote:
        if choice not in VALID_VOTE_CHOICES:
            raise RuleViolation(f"choice 仅支持 {'/'.join(VALID_VOTE_CHOICES)}")
        if voter_type not in VALID_VOTER_TYPES:
            raise RuleViolation("voter_type 仅支持 human/ai")
        return cls(
            id=vote_id,
            meeting_id=meeting_id,
            subject=subject,
            voter_type=voter_type,
            voter_id=voter_id,
            choice=choice,
            comment=comment,
            create_time=create_time,
        )


@dataclass(slots=True)
class Resolution:
    id: uuid.UUID
    meeting_id: uuid.UUID
    content: str
    owner_id: uuid.UUID | None
    due_date: date | None
    is_confirmed: bool
    confirmed_by: uuid.UUID | None
    converted_task_id: uuid.UUID | None
    create_time: datetime

    def confirm(
        self,
        *,
        actor_id: uuid.UUID,
        actor_type: ConfirmationActorType,
    ) -> None:
        if actor_type is not ConfirmationActorType.HUMAN:
            raise RuleViolation("决议只能由真人确认")
        self.is_confirmed = True
        self.confirmed_by = actor_id

    def assert_convertible(self) -> None:
        if not self.is_confirmed:
            raise RuleViolation("决议未经真人确认，不可转任务卡（决议须真人确认生效）")
        if self.converted_task_id is not None:
            raise RuleViolation("该决议已转过任务卡")

    def record_conversion(self, task_id: uuid.UUID) -> None:
        self.assert_convertible()
        self.converted_task_id = task_id


def parse_vote_choice(text: str) -> str:
    """Parse only an explicit first-line advisory choice."""
    lines = (text or "").strip().splitlines()
    first = lines[0].lower().lstrip("*# \t-—：:") if lines else ""
    for choice in VALID_VOTE_CHOICES:
        if first.startswith(choice):
            return choice
    return "abstain"
