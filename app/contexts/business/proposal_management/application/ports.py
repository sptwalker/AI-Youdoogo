"""Proposal-owned persistence, transaction, policy, and collaboration ports."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, Self

from app.contexts.business.proposal_management.application.contracts import (
    ProposalViewer,
    TaskResult,
)
from app.contexts.business.proposal_management.domain.models import Proposal, ProposalReview


@dataclass(frozen=True, slots=True)
class ProposalVisibility:
    """Persistence-neutral row filter produced by the visibility policy."""

    unrestricted: bool
    viewer_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class ExpertReference:
    """Stable expert identity used by the research adapter."""

    id: uuid.UUID
    name: str


@dataclass(frozen=True, slots=True)
class ExpertResearchRequest:
    """Plain research input with no Agent runtime or ORM objects."""

    task_type: str
    input_summary: str
    user_message: str
    operator_id: uuid.UUID | None


@dataclass(frozen=True, slots=True)
class ExpertResearchResult:
    """Normalized expert output after the optional reflection loop."""

    conclusion: str


@dataclass(frozen=True, slots=True)
class TaskCreationRequest:
    """Plain request to Task Management's compatibility adapter."""

    title: str
    task_type: str
    creator_id: uuid.UUID
    priority: str
    assignee_agent_id: uuid.UUID | None
    payload: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class AuditRequest:
    actor_id: uuid.UUID | None
    actor_role: str | None
    action: str
    summary: str
    target_type: str
    target_id: uuid.UUID


class ProposalRepository(Protocol):
    async def add(self, proposal: Proposal) -> None: ...

    async def get(self, proposal_id: uuid.UUID) -> Proposal | None: ...

    async def save(self, proposal: Proposal) -> None: ...

    async def list_proposals(
        self,
        *,
        status: str | None,
        limit: int,
        visibility: ProposalVisibility,
    ) -> list[Proposal]: ...

    async def add_review(self, review: ProposalReview) -> None: ...

    async def list_reviews(self, proposal_id: uuid.UUID) -> list[ProposalReview]: ...


class ProposalUnitOfWork(Protocol):
    @property
    def proposals(self) -> ProposalRepository: ...

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object | None,
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


ProposalUnitOfWorkFactory = Callable[[], ProposalUnitOfWork]


class ExpertResearchPort(Protocol):
    async def find_expert(self, name: str) -> ExpertReference | None: ...

    async def research(
        self, expert: ExpertReference, request: ExpertResearchRequest
    ) -> ExpertResearchResult: ...


class TaskCreationPort(Protocol):
    async def create_task(self, request: TaskCreationRequest) -> TaskResult: ...


class ProposalVisibilityPolicy(Protocol):
    def visibility_for(self, viewer: ProposalViewer | None) -> ProposalVisibility: ...

    def ensure_visible(self, viewer: ProposalViewer | None, proposal: Proposal) -> None: ...


class AuditPort(Protocol):
    async def record(self, request: AuditRequest) -> None: ...


class Clock(Protocol):
    def now(self) -> datetime: ...


class IdentifierPort(Protocol):
    def new_id(self) -> uuid.UUID: ...

    def new_proposal_code(self) -> str: ...
