"""Proposal lifecycle use cases coordinated through Proposal-owned ports."""

from __future__ import annotations

import uuid

from app.contexts.business.proposal_management.application.contracts import (
    ConvertProposalCommand,
    CreateProposalCommand,
    GetProposalQuery,
    ListProposalsQuery,
    ProposalDetailResult,
    ProposalResult,
    ProposalReviewResult,
    ResearchProposalCommand,
    ReviewProposalCommand,
    TaskResult,
)
from app.contexts.business.proposal_management.application.errors import (
    ProposalExpertUnavailable,
    ProposalNotFound,
)
from app.contexts.business.proposal_management.application.ports import (
    AuditPort,
    AuditRequest,
    Clock,
    ExpertResearchPort,
    ExpertResearchRequest,
    IdentifierPort,
    ProposalRepository,
    ProposalUnitOfWorkFactory,
    ProposalVisibilityPolicy,
    TaskCreationPort,
    TaskCreationRequest,
)
from app.contexts.business.proposal_management.domain.models import Proposal, ProposalReview

EXPERT_NAME = "会商AI专家"


def _proposal_result(proposal: Proposal) -> ProposalResult:
    return ProposalResult(
        id=proposal.id,
        code=proposal.code,
        title=proposal.title,
        department_id=proposal.department_id,
        background=proposal.background,
        plan=proposal.plan,
        benefit_risk=proposal.benefit_risk,
        priority=proposal.priority,
        status=proposal.status.value,
        creator_id=proposal.creator_id,
        converted_task_id=proposal.converted_task_id,
        create_time=proposal.create_time,
    )


def _review_result(review: ProposalReview) -> ProposalReviewResult:
    return ProposalReviewResult(
        id=review.id,
        proposal_id=review.proposal_id,
        review_type=review.review_type.value,
        conclusion=review.conclusion,
        reviewer_id=review.reviewer_id,
        decision=review.decision.value if review.decision is not None else None,
        create_time=review.create_time,
    )


class ProposalApplication:
    """Deep Application boundary owning Proposal orchestration and commits."""

    def __init__(
        self,
        *,
        uow_factory: ProposalUnitOfWorkFactory,
        research_port: ExpertResearchPort,
        task_port: TaskCreationPort,
        visibility_policy: ProposalVisibilityPolicy,
        audit_port: AuditPort,
        clock: Clock,
        identifiers: IdentifierPort,
    ) -> None:
        self._uow_factory = uow_factory
        self._research_port = research_port
        self._task_port = task_port
        self._visibility_policy = visibility_policy
        self._audit_port = audit_port
        self._clock = clock
        self._identifiers = identifiers

    async def create(self, command: CreateProposalCommand) -> ProposalResult:
        proposal = Proposal(
            id=self._identifiers.new_id(),
            code=self._identifiers.new_proposal_code(),
            title=command.title,
            background=command.background,
            plan=command.plan,
            benefit_risk=command.benefit_risk,
            priority=command.priority,
            creator_id=command.creator_id,
            department_id=command.department_id,
            create_time=self._clock.now(),
        )
        async with self._uow_factory() as uow:
            await uow.proposals.add(proposal)
            await uow.commit()
        return _proposal_result(proposal)

    async def get(self, query: GetProposalQuery) -> ProposalResult:
        async with self._uow_factory() as uow:
            proposal = await self._get_required(uow.proposals, query.proposal_id)
            self._visibility_policy.ensure_visible(query.viewer, proposal)
        return _proposal_result(proposal)

    async def detail(self, query: GetProposalQuery) -> ProposalDetailResult:
        async with self._uow_factory() as uow:
            proposal = await self._get_required(uow.proposals, query.proposal_id)
            self._visibility_policy.ensure_visible(query.viewer, proposal)
            reviews = await uow.proposals.list_reviews(query.proposal_id)
        return ProposalDetailResult(
            proposal=_proposal_result(proposal),
            reviews=tuple(_review_result(review) for review in reviews),
        )

    async def list(self, query: ListProposalsQuery) -> tuple[ProposalResult, ...]:
        visibility = self._visibility_policy.visibility_for(query.viewer)
        async with self._uow_factory() as uow:
            proposals = await uow.proposals.list_proposals(
                status=query.status,
                limit=query.limit,
                visibility=visibility,
            )
        return tuple(_proposal_result(proposal) for proposal in proposals)

    async def list_reviews(self, proposal_id: uuid.UUID) -> tuple[ProposalReviewResult, ...]:
        async with self._uow_factory() as uow:
            reviews = await uow.proposals.list_reviews(proposal_id)
        return tuple(_review_result(review) for review in reviews)

    async def research(self, command: ResearchProposalCommand) -> ProposalReviewResult:
        # Preserve legacy failure order: Proposal/lifecycle validation precedes expert lookup.
        async with self._uow_factory() as uow:
            proposal = await self._get_required(uow.proposals, command.proposal_id)
            proposal.assert_research_allowed()

        expert = await self._research_port.find_expert(EXPERT_NAME)
        if expert is None:
            raise ProposalExpertUnavailable()

        async with self._uow_factory() as uow:
            proposal = await self._get_required(uow.proposals, command.proposal_id)
            proposal.start_research()
            await uow.proposals.save(proposal)
            await uow.commit()

        user_message = (
            f"请对以下提案做会前预研：\n\n提案标题：{proposal.title}\n"
            f"背景：{proposal.background}\n方案：{proposal.plan}\n"
            f"收益与风险：{proposal.benefit_risk or '（未填写）'}"
        )
        research = await self._research_port.research(
            expert,
            ExpertResearchRequest(
                task_type="proposal_research",
                input_summary=f"提案预研：{proposal.code}",
                user_message=user_message,
                operator_id=command.operator_id,
            ),
        )

        async with self._uow_factory() as uow:
            current = await self._get_required(uow.proposals, command.proposal_id)
            review = current.complete_research(
                review_id=self._identifiers.new_id(),
                conclusion=research.conclusion,
                occurred_at=self._clock.now(),
            )
            await uow.proposals.add_review(review)
            await uow.proposals.save(current)
            await uow.commit()
        return _review_result(review)

    async def review(self, command: ReviewProposalCommand) -> ProposalResult:
        async with self._uow_factory() as uow:
            proposal = await self._get_required(uow.proposals, command.proposal_id)
            review = proposal.record_human_review(
                review_id=self._identifiers.new_id(),
                reviewer_id=command.reviewer_id,
                conclusion=command.conclusion,
                decision=command.decision,
                occurred_at=self._clock.now(),
            )
            await uow.proposals.add_review(review)
            await uow.proposals.save(proposal)
            await uow.commit()

        if command.actor_role is not None:
            await self._audit_port.record(
                AuditRequest(
                    actor_id=command.reviewer_id,
                    actor_role=command.actor_role,
                    action=f"proposal.{command.decision}",
                    summary=f"提案评审 {proposal.code} → {command.decision}",
                    target_type="proposal_card",
                    target_id=proposal.id,
                )
            )
        return _proposal_result(proposal)

    async def convert(self, command: ConvertProposalCommand) -> TaskResult:
        async with self._uow_factory() as uow:
            proposal = await self._get_required(uow.proposals, command.proposal_id)
            proposal.assert_convertible()
            task = await self._task_port.create_task(
                TaskCreationRequest(
                    title=f"[提案落地] {proposal.title}",
                    task_type="proposal_execution",
                    creator_id=command.creator_id,
                    priority=proposal.priority,
                    assignee_agent_id=command.assignee_agent_id,
                    payload=(("proposal_code", proposal.code), ("plan", proposal.plan)),
                )
            )
            proposal.record_conversion(task.id)
            await uow.proposals.save(proposal)
            await uow.commit()

        if command.actor_role is not None:
            await self._audit_port.record(
                AuditRequest(
                    actor_id=command.creator_id,
                    actor_role=command.actor_role,
                    action="proposal.convert",
                    summary=f"提案转任务卡 {task.title[:40]}",
                    target_type="task_card",
                    target_id=task.id,
                )
            )
        return task

    @staticmethod
    async def _get_required(
        repository: ProposalRepository, proposal_id: uuid.UUID
    ) -> Proposal:
        proposal = await repository.get(proposal_id)
        if proposal is None:
            raise ProposalNotFound()
        return proposal
