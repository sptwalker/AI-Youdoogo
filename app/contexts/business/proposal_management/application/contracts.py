"""Plain commands and results published by Proposal Management Application."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class ProposalViewer:
    """Only the principal fields needed for Proposal row visibility."""

    id: uuid.UUID
    role_code: str
    department_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class CreateProposalCommand:
    title: str
    background: str
    plan: str
    creator_id: uuid.UUID
    benefit_risk: str | None = None
    priority: str = "normal"
    department_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class GetProposalQuery:
    proposal_id: uuid.UUID
    viewer: ProposalViewer | None = None


@dataclass(frozen=True, slots=True)
class ListProposalsQuery:
    status: str | None = None
    limit: int = 100
    viewer: ProposalViewer | None = None


@dataclass(frozen=True, slots=True)
class ResearchProposalCommand:
    proposal_id: uuid.UUID
    operator_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class ReviewProposalCommand:
    proposal_id: uuid.UUID
    reviewer_id: uuid.UUID
    conclusion: str
    decision: str
    actor_role: str | None = None


@dataclass(frozen=True, slots=True)
class ConvertProposalCommand:
    proposal_id: uuid.UUID
    creator_id: uuid.UUID
    assignee_agent_id: uuid.UUID | None = None
    actor_role: str | None = None


@dataclass(frozen=True, slots=True)
class ProposalResult:
    id: uuid.UUID
    code: str
    title: str
    department_id: uuid.UUID | None
    background: str
    plan: str
    benefit_risk: str | None
    priority: str
    status: str
    creator_id: uuid.UUID
    converted_task_id: uuid.UUID | None
    create_time: datetime


@dataclass(frozen=True, slots=True)
class ProposalReviewResult:
    id: uuid.UUID
    proposal_id: uuid.UUID
    review_type: str
    conclusion: str
    reviewer_id: uuid.UUID | None
    decision: str | None
    create_time: datetime


@dataclass(frozen=True, slots=True)
class ProposalDetailResult:
    proposal: ProposalResult
    reviews: tuple[ProposalReviewResult, ...]


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
