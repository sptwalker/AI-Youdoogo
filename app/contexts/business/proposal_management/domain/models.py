"""Framework-independent Proposal aggregate and review values."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from app.contexts.business.proposal_management.domain.errors import (
    InvalidProposalDecision,
    ProposalAlreadyConverted,
    ProposalNotApproved,
    ProposalNotDraft,
    ProposalResearchNotAllowed,
    ProposalReviewNotAllowed,
)


class ProposalStatus(StrEnum):
    """Persisted Proposal lifecycle states."""

    DRAFT = "draft"
    RESEARCHING = "researching"
    REVIEWED = "reviewed"
    APPROVED = "approved"
    REJECTED = "rejected"


class ProposalDecision(StrEnum):
    """Human decisions accepted by Proposal Management."""

    APPROVE = "approve"
    REJECT = "reject"


class ProposalReviewType(StrEnum):
    """Persisted Proposal review kinds."""

    AI_RESEARCH = "ai_research"
    HUMAN = "human"


@dataclass(frozen=True, slots=True)
class ProposalReview:
    """An immutable review produced by AI research or a human decision."""

    id: uuid.UUID
    proposal_id: uuid.UUID
    review_type: ProposalReviewType
    conclusion: str
    reviewer_id: uuid.UUID | None
    decision: ProposalDecision | None
    create_time: datetime


@dataclass(slots=True)
class Proposal:
    """Proposal aggregate owning lifecycle transitions and conversion uniqueness."""

    id: uuid.UUID
    code: str
    title: str
    background: str
    plan: str
    creator_id: uuid.UUID
    create_time: datetime
    benefit_risk: str | None = None
    priority: str = "normal"
    department_id: uuid.UUID | None = None
    status: ProposalStatus = ProposalStatus.DRAFT
    converted_task_id: uuid.UUID | None = None

    def assert_research_allowed(self) -> None:
        """Reject research once a human decision has made the Proposal terminal."""
        if self.status in (ProposalStatus.APPROVED, ProposalStatus.REJECTED):
            raise ProposalResearchNotAllowed()

    def edit_draft(
        self,
        *,
        title: str,
        background: str,
        plan: str,
        benefit_risk: str | None,
        priority: str,
    ) -> None:
        """Amend a still-draft proposal; forbidden once预研/评审已启动。"""
        if self.status != ProposalStatus.DRAFT:
            raise ProposalNotDraft(self.status.value)
        self.title = title
        self.background = background
        self.plan = plan
        self.benefit_risk = benefit_risk
        self.priority = priority

    def assert_deletable(self) -> None:
        """Only a draft may be removed; reviewed/approved proposals keep their trail."""
        if self.status != ProposalStatus.DRAFT:
            raise ProposalNotDraft(self.status.value)

    def start_research(self) -> None:
        """Expose the durable pending state before invoking an AI expert."""
        self.assert_research_allowed()
        self.status = ProposalStatus.RESEARCHING

    def complete_research(
        self,
        *,
        review_id: uuid.UUID,
        conclusion: str,
        occurred_at: datetime,
    ) -> ProposalReview:
        """Record AI evidence without making a human approval decision."""
        if self.status != ProposalStatus.RESEARCHING:
            raise ProposalResearchNotAllowed()
        self.status = ProposalStatus.REVIEWED
        return ProposalReview(
            id=review_id,
            proposal_id=self.id,
            review_type=ProposalReviewType.AI_RESEARCH,
            conclusion=conclusion,
            reviewer_id=None,
            decision=None,
            create_time=occurred_at,
        )

    def record_human_review(
        self,
        *,
        review_id: uuid.UUID,
        reviewer_id: uuid.UUID,
        conclusion: str,
        decision: str,
        occurred_at: datetime,
    ) -> ProposalReview:
        """Apply the only transition that may approve or reject a Proposal."""
        try:
            normalized = ProposalDecision(decision)
        except ValueError as exc:
            raise InvalidProposalDecision() from exc
        if self.status != ProposalStatus.REVIEWED:
            raise ProposalReviewNotAllowed(self.status.value)

        self.status = (
            ProposalStatus.APPROVED
            if normalized is ProposalDecision.APPROVE
            else ProposalStatus.REJECTED
        )
        return ProposalReview(
            id=review_id,
            proposal_id=self.id,
            review_type=ProposalReviewType.HUMAN,
            conclusion=conclusion,
            reviewer_id=reviewer_id,
            decision=normalized,
            create_time=occurred_at,
        )

    def assert_convertible(self) -> None:
        """Guard approval and at-most-once conversion before creating work."""
        if self.status != ProposalStatus.APPROVED:
            raise ProposalNotApproved()
        if self.converted_task_id is not None:
            raise ProposalAlreadyConverted()

    def record_conversion(self, task_id: uuid.UUID) -> None:
        """Retain the Task identifier after the Task port succeeds."""
        self.assert_convertible()
        self.converted_task_id = task_id
