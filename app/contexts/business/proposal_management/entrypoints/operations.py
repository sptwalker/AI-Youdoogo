"""Request-scoped Proposal entrypoint used by HTTP and compatibility callers."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.business.proposal_management.application.contracts import (
    ConvertProposalCommand,
    CreateProposalCommand,
    DeleteProposalCommand,
    EditProposalCommand,
    GetProposalQuery,
    ListProposalsQuery,
    ProposalDetailResult,
    ProposalResult,
    ProposalReviewResult,
    ProposalViewer,
    ResearchProposalCommand,
    ReviewProposalCommand,
    TaskResult,
)
from app.contexts.business.proposal_management.infrastructure.composition import (
    build_proposal_application,
)


async def create_proposal(
    session: AsyncSession,
    *,
    title: str,
    background: str,
    plan: str,
    creator_id: uuid.UUID,
    benefit_risk: str | None = None,
    priority: str = "normal",
    department_id: uuid.UUID | None = None,
) -> ProposalResult:
    return await build_proposal_application(session).create(
        CreateProposalCommand(
            title=title,
            background=background,
            plan=plan,
            creator_id=creator_id,
            benefit_risk=benefit_risk,
            priority=priority,
            department_id=department_id,
        )
    )


async def edit_proposal(
    session: AsyncSession,
    proposal_id: uuid.UUID,
    *,
    actor_id: uuid.UUID,
    title: str,
    background: str,
    plan: str,
    benefit_risk: str | None = None,
    priority: str = "normal",
) -> ProposalResult:
    return await build_proposal_application(session).edit(
        EditProposalCommand(
            proposal_id=proposal_id,
            actor_id=actor_id,
            title=title,
            background=background,
            plan=plan,
            benefit_risk=benefit_risk,
            priority=priority,
        )
    )


async def delete_proposal(
    session: AsyncSession,
    proposal_id: uuid.UUID,
    *,
    actor_id: uuid.UUID,
) -> None:
    await build_proposal_application(session).delete(
        DeleteProposalCommand(proposal_id=proposal_id, actor_id=actor_id)
    )


async def get_proposal(
    session: AsyncSession,
    proposal_id: uuid.UUID,
    *,
    viewer: ProposalViewer | None = None,
) -> ProposalResult:
    return await build_proposal_application(session).get(
        GetProposalQuery(proposal_id=proposal_id, viewer=viewer)
    )


async def get_proposal_detail(
    session: AsyncSession,
    proposal_id: uuid.UUID,
    *,
    viewer: ProposalViewer | None = None,
) -> ProposalDetailResult:
    return await build_proposal_application(session).detail(
        GetProposalQuery(proposal_id=proposal_id, viewer=viewer)
    )


async def list_proposals(
    session: AsyncSession,
    *,
    status: str | None = None,
    limit: int = 100,
    viewer: ProposalViewer | None = None,
) -> tuple[ProposalResult, ...]:
    return await build_proposal_application(session).list(
        ListProposalsQuery(status=status, limit=limit, viewer=viewer)
    )


async def list_reviews(
    session: AsyncSession, proposal_id: uuid.UUID
) -> tuple[ProposalReviewResult, ...]:
    return await build_proposal_application(session).list_reviews(proposal_id)


async def run_ai_research(
    session: AsyncSession,
    proposal_id: uuid.UUID,
    *,
    operator_id: uuid.UUID | None = None,
) -> ProposalReviewResult:
    return await build_proposal_application(session).research(
        ResearchProposalCommand(proposal_id=proposal_id, operator_id=operator_id)
    )


async def human_review(
    session: AsyncSession,
    proposal_id: uuid.UUID,
    *,
    reviewer_id: uuid.UUID,
    conclusion: str,
    decision: str,
    actor_role: str | None = None,
) -> ProposalResult:
    return await build_proposal_application(session).review(
        ReviewProposalCommand(
            proposal_id=proposal_id,
            reviewer_id=reviewer_id,
            conclusion=conclusion,
            decision=decision,
            actor_role=actor_role,
        )
    )


async def convert_to_task(
    session: AsyncSession,
    proposal_id: uuid.UUID,
    *,
    creator_id: uuid.UUID,
    assignee_agent_id: uuid.UUID | None = None,
    actor_role: str | None = None,
) -> TaskResult:
    return await build_proposal_application(session).convert(
        ConvertProposalCommand(
            proposal_id=proposal_id,
            creator_id=creator_id,
            assignee_agent_id=assignee_agent_id,
            actor_role=actor_role,
        )
    )
