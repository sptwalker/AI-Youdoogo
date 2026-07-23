"""One-way compatibility facade for Proposal Management."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.business.proposal_management import ProposalError
from app.contexts.business.proposal_management.application.contracts import (
    ProposalResult,
    ProposalReviewResult,
    ProposalViewer,
    TaskResult,
)
from app.contexts.business.proposal_management.application.use_cases import EXPERT_NAME
from app.contexts.business.proposal_management.entrypoints import operations

if TYPE_CHECKING:
    from app.models.system import SysUser

__all__ = [
    "EXPERT_NAME",
    "ProposalError",
    "convert_to_task",
    "create_proposal",
    "get_proposal",
    "human_review",
    "list_proposals",
    "list_reviews",
    "run_ai_research",
]


def _viewer(user: SysUser | None) -> ProposalViewer | None:
    if user is None:
        return None
    return ProposalViewer(
        id=user.id,
        role_code=user.role_code,
        department_id=user.department_id,
    )


async def create_proposal(
    db: AsyncSession,
    *,
    title: str,
    background: str,
    plan: str,
    creator_id: uuid.UUID,
    benefit_risk: str | None = None,
    priority: str = "normal",
    department_id: uuid.UUID | None = None,
) -> ProposalResult:
    return await operations.create_proposal(
        db,
        title=title,
        background=background,
        plan=plan,
        creator_id=creator_id,
        benefit_risk=benefit_risk,
        priority=priority,
        department_id=department_id,
    )


async def get_proposal(db: AsyncSession, proposal_id: uuid.UUID) -> ProposalResult:
    return await operations.get_proposal(db, proposal_id)


async def run_ai_research(
    db: AsyncSession,
    proposal_id: uuid.UUID,
    *,
    operator_id: uuid.UUID | None = None,
) -> ProposalReviewResult:
    return await operations.run_ai_research(db, proposal_id, operator_id=operator_id)


async def human_review(
    db: AsyncSession,
    proposal_id: uuid.UUID,
    *,
    reviewer_id: uuid.UUID,
    conclusion: str,
    decision: str,
) -> ProposalResult:
    return await operations.human_review(
        db,
        proposal_id,
        reviewer_id=reviewer_id,
        conclusion=conclusion,
        decision=decision,
    )


async def convert_to_task(
    db: AsyncSession,
    proposal_id: uuid.UUID,
    *,
    creator_id: uuid.UUID,
    assignee_agent_id: uuid.UUID | None = None,
) -> TaskResult:
    return await operations.convert_to_task(
        db,
        proposal_id,
        creator_id=creator_id,
        assignee_agent_id=assignee_agent_id,
    )


async def list_proposals(
    db: AsyncSession,
    *,
    status: str | None = None,
    limit: int = 100,
    viewer: SysUser | None = None,
) -> tuple[ProposalResult, ...]:
    return await operations.list_proposals(
        db,
        status=status,
        limit=limit,
        viewer=_viewer(viewer),
    )


async def list_reviews(
    db: AsyncSession, proposal_id: uuid.UUID
) -> tuple[ProposalReviewResult, ...]:
    return await operations.list_reviews(db, proposal_id)
