"""Proposal aggregate rules without persistence, HTTP, Agent, or Task dependencies."""

import uuid
from datetime import UTC, datetime

import pytest

from app.contexts.business.proposal_management.domain import (
    InvalidProposalDecision,
    Proposal,
    ProposalAlreadyConverted,
    ProposalNotApproved,
    ProposalResearchNotAllowed,
    ProposalReviewNotAllowed,
    ProposalStatus,
)


def _proposal(status: ProposalStatus = ProposalStatus.DRAFT) -> Proposal:
    return Proposal(
        id=uuid.uuid4(),
        code="PROP-TEST0001",
        title="上线会员体系",
        background="留存低",
        plan="推出会员权益",
        creator_id=uuid.uuid4(),
        create_time=datetime.now(UTC),
        status=status,
    )


def test_ai_research_only_advances_to_reviewed() -> None:
    proposal = _proposal()
    proposal.start_research()
    assert proposal.status is ProposalStatus.RESEARCHING

    review = proposal.complete_research(
        review_id=uuid.uuid4(),
        conclusion="建议补充成本测算",
        occurred_at=datetime.now(UTC),
    )

    assert proposal.status is ProposalStatus.REVIEWED
    assert review.decision is None
    assert review.reviewer_id is None


@pytest.mark.parametrize(
    ("decision", "expected"),
    [("approve", ProposalStatus.APPROVED), ("reject", ProposalStatus.REJECTED)],
)
def test_only_human_review_creates_terminal_decision(
    decision: str, expected: ProposalStatus
) -> None:
    proposal = _proposal(ProposalStatus.REVIEWED)

    review = proposal.record_human_review(
        review_id=uuid.uuid4(),
        reviewer_id=uuid.uuid4(),
        conclusion="真人结论",
        decision=decision,
        occurred_at=datetime.now(UTC),
    )

    assert proposal.status is expected
    assert review.decision is not None and review.decision.value == decision


def test_invalid_transitions_leave_state_unchanged() -> None:
    approved = _proposal(ProposalStatus.APPROVED)
    with pytest.raises(ProposalResearchNotAllowed):
        approved.start_research()
    assert approved.status is ProposalStatus.APPROVED

    draft = _proposal()
    with pytest.raises(ProposalReviewNotAllowed):
        draft.record_human_review(
            review_id=uuid.uuid4(),
            reviewer_id=uuid.uuid4(),
            conclusion="越级评审",
            decision="approve",
            occurred_at=datetime.now(UTC),
        )
    assert draft.status is ProposalStatus.DRAFT

    with pytest.raises(InvalidProposalDecision):
        draft.record_human_review(
            review_id=uuid.uuid4(),
            reviewer_id=uuid.uuid4(),
            conclusion="无效决议",
            decision="abstain",
            occurred_at=datetime.now(UTC),
        )


def test_conversion_requires_approval_and_is_at_most_once() -> None:
    with pytest.raises(ProposalNotApproved):
        _proposal().record_conversion(uuid.uuid4())

    approved = _proposal(ProposalStatus.APPROVED)
    task_id = uuid.uuid4()
    approved.record_conversion(task_id)
    assert approved.converted_task_id == task_id

    with pytest.raises(ProposalAlreadyConverted):
        approved.record_conversion(uuid.uuid4())
