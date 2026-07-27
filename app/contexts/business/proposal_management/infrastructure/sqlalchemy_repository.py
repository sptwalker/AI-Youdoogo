"""SQLAlchemy mapper and repository for the existing Proposal tables."""

from __future__ import annotations

import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.business.proposal_management.application.ports import ProposalVisibility
from app.contexts.business.proposal_management.domain.models import (
    Proposal,
    ProposalDecision,
    ProposalReview,
    ProposalReviewType,
    ProposalStatus,
)
from app.models.proposal import (
    ProposalCard,
)
from app.models.proposal import (
    ProposalReview as ProposalReviewRow,
)


def proposal_to_domain(row: ProposalCard) -> Proposal:
    """Translate an existing ORM row into the owned aggregate."""
    return Proposal(
        id=row.id,
        code=row.code,
        title=row.title,
        background=row.background,
        plan=row.plan,
        benefit_risk=row.benefit_risk,
        priority=row.priority,
        creator_id=row.creator_id,
        department_id=row.department_id,
        status=ProposalStatus(row.status),
        converted_task_id=row.converted_task_id,
        create_time=row.create_time,
    )


def review_to_domain(row: ProposalReviewRow) -> ProposalReview:
    """Translate an existing review row without a data migration."""
    return ProposalReview(
        id=row.id,
        proposal_id=row.proposal_id,
        review_type=ProposalReviewType(row.review_type),
        conclusion=row.conclusion,
        reviewer_id=row.reviewer_id,
        decision=ProposalDecision(row.decision) if row.decision is not None else None,
        create_time=row.create_time,
    )


class SQLAlchemyProposalRepository:
    """Proposal persistence adapter; methods flush but never commit."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._tracked: dict[uuid.UUID, ProposalCard] = {}

    async def add(self, proposal: Proposal) -> None:
        row = ProposalCard(
            id=proposal.id,
            code=proposal.code,
            title=proposal.title,
            background=proposal.background,
            plan=proposal.plan,
            benefit_risk=proposal.benefit_risk,
            priority=proposal.priority,
            creator_id=proposal.creator_id,
            department_id=proposal.department_id,
            status=proposal.status.value,
            converted_task_id=proposal.converted_task_id,
            create_time=proposal.create_time,
        )
        self._session.add(row)
        await self._session.flush()
        self._tracked[proposal.id] = row

    async def get(self, proposal_id: uuid.UUID) -> Proposal | None:
        row = await self._session.get(ProposalCard, proposal_id)
        if row is None or row.is_delete:
            return None
        self._tracked[proposal_id] = row
        return proposal_to_domain(row)

    async def save(self, proposal: Proposal) -> None:
        row = self._tracked.get(proposal.id)
        if row is None:
            row = await self._session.get(ProposalCard, proposal.id)
        if row is None or row.is_delete:
            return
        row.title = proposal.title
        row.background = proposal.background
        row.plan = proposal.plan
        row.benefit_risk = proposal.benefit_risk
        row.priority = proposal.priority
        row.department_id = proposal.department_id
        row.status = proposal.status.value
        row.converted_task_id = proposal.converted_task_id
        await self._session.flush()
        self._tracked[proposal.id] = row

    async def delete(self, proposal_id: uuid.UUID) -> None:
        # 软删除，与 get/list 的 is_delete 过滤一致（不做物理删，保留潜在追溯）。
        row = self._tracked.get(proposal_id)
        if row is None:
            row = await self._session.get(ProposalCard, proposal_id)
        if row is None or row.is_delete:
            return
        row.is_delete = True
        await self._session.flush()
        self._tracked.pop(proposal_id, None)

    async def list_proposals(
        self,
        *,
        status: str | None,
        limit: int,
        visibility: ProposalVisibility,
    ) -> list[Proposal]:
        stmt = select(ProposalCard).where(ProposalCard.is_delete.is_(False))
        if status is not None:
            stmt = stmt.where(ProposalCard.status == status)
        if not visibility.unrestricted and visibility.viewer_id is not None:
            conditions = [ProposalCard.creator_id == visibility.viewer_id]
            if visibility.department_id is not None:
                conditions.append(ProposalCard.department_id == visibility.department_id)
            stmt = stmt.where(or_(*conditions))
        stmt = stmt.order_by(ProposalCard.create_time.desc()).limit(limit)
        rows = list((await self._session.execute(stmt)).scalars())
        for row in rows:
            self._tracked[row.id] = row
        return [proposal_to_domain(row) for row in rows]

    async def add_review(self, review: ProposalReview) -> None:
        self._session.add(
            ProposalReviewRow(
                id=review.id,
                proposal_id=review.proposal_id,
                review_type=review.review_type.value,
                conclusion=review.conclusion,
                reviewer_id=review.reviewer_id,
                decision=review.decision.value if review.decision is not None else None,
                create_time=review.create_time,
            )
        )
        await self._session.flush()

    async def list_reviews(self, proposal_id: uuid.UUID) -> list[ProposalReview]:
        stmt = (
            select(ProposalReviewRow)
            .where(ProposalReviewRow.proposal_id == proposal_id)
            .order_by(ProposalReviewRow.create_time)
        )
        return [review_to_domain(row) for row in (await self._session.execute(stmt)).scalars()]
