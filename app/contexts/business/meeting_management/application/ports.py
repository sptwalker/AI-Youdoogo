"""Meeting-owned persistence, policy, AI-advisory, and Task ports."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol, Self

from app.contexts.business.meeting_management.application.contracts import TaskResult
from app.contexts.business.meeting_management.domain.models import (
    Discussion,
    Meeting,
    Resolution,
    Vote,
)
from app.contexts.foundations.identity.contracts import Principal


@dataclass(frozen=True, slots=True)
class MeetingVisibility:
    unrestricted: bool
    creator_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None


class MeetingRepository(Protocol):
    async def add_meeting(self, meeting: Meeting) -> None: ...

    async def get_meeting(self, meeting_id: uuid.UUID) -> Meeting | None: ...

    async def save_meeting(self, meeting: Meeting) -> None: ...

    async def list_meetings(
        self,
        *,
        status: str | None,
        limit: int,
        visibility: MeetingVisibility,
    ) -> tuple[Meeting, ...]: ...

    async def add_discussion(self, discussion: Discussion) -> None: ...

    async def list_discussions(self, meeting_id: uuid.UUID) -> tuple[Discussion, ...]: ...

    async def add_vote(self, vote: Vote) -> None: ...

    async def list_votes(self, meeting_id: uuid.UUID, subject: str) -> tuple[Vote, ...]: ...

    async def add_resolution(self, resolution: Resolution) -> None: ...

    async def get_resolution(
        self, resolution_id: uuid.UUID, *, for_update: bool = False
    ) -> Resolution | None: ...

    async def save_resolution(self, resolution: Resolution) -> None: ...

    async def list_resolutions(self, meeting_id: uuid.UUID) -> tuple[Resolution, ...]: ...


class MeetingUnitOfWork(Protocol):
    @property
    def meetings(self) -> MeetingRepository: ...

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object | None,
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


MeetingUnitOfWorkFactory = Callable[[], MeetingUnitOfWork]


class MeetingVisibilityPolicy(Protocol):
    def visibility_for(self, principal: Principal | None) -> MeetingVisibility: ...

    def ensure_visible(self, principal: Principal | None, meeting: Meeting) -> None: ...


class AdvisoryEventKind(StrEnum):
    STARTED = "started"
    DELTA = "delta"
    COMPLETED = "completed"


@dataclass(frozen=True, slots=True)
class AdvisoryStreamEvent:
    kind: AdvisoryEventKind
    expert_id: uuid.UUID
    expert_name: str
    text: str = ""


@dataclass(frozen=True, slots=True)
class AdvisoryResult:
    expert_id: uuid.UUID
    expert_name: str
    content: str
    comment: str | None = None


@dataclass(frozen=True, slots=True)
class SpeechAdvisoryRequest:
    topic: str
    history: tuple[tuple[str, str], ...]
    operator_id: uuid.UUID | None


@dataclass(frozen=True, slots=True)
class VoteAdvisoryRequest:
    subject: str
    operator_id: uuid.UUID | None


@dataclass(frozen=True, slots=True)
class MinutesAdvisoryRequest:
    title: str
    discussions: tuple[tuple[str, str, str], ...]
    operator_id: uuid.UUID | None


class MeetingAdvisoryPort(Protocol):
    def speak(self, request: SpeechAdvisoryRequest) -> AsyncIterator[AdvisoryStreamEvent]: ...

    async def vote(self, request: VoteAdvisoryRequest) -> AdvisoryResult: ...

    async def minutes(self, request: MinutesAdvisoryRequest) -> AdvisoryResult: ...


@dataclass(frozen=True, slots=True)
class TaskCreationRequest:
    title: str
    task_type: str
    creator_id: uuid.UUID
    assignee_agent_id: uuid.UUID | None
    payload: tuple[tuple[str, str], ...]


class TaskCreationPort(Protocol):
    async def create_task(self, request: TaskCreationRequest) -> TaskResult: ...


class Clock(Protocol):
    def now(self) -> datetime: ...


class IdentifierPort(Protocol):
    def new_id(self) -> uuid.UUID: ...
