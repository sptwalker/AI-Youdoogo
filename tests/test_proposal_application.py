"""Proposal Application orchestration with fake ports and Unit of Work."""

from __future__ import annotations

import copy
import uuid
from collections import deque
from datetime import UTC, datetime

import pytest

from app.contexts.business.proposal_management.application.contracts import (
    ConvertProposalCommand,
    CreateProposalCommand,
    DeleteProposalCommand,
    EditProposalCommand,
    ProposalResult,
    ProposalViewer,
    ResearchProposalCommand,
    ReviewProposalCommand,
    TaskResult,
)
from app.contexts.business.proposal_management.application.errors import (
    ProposalError,
    ProposalNotFound,
)
from app.contexts.business.proposal_management.application.ports import (
    AuditRequest,
    ExpertReference,
    ExpertResearchRequest,
    ExpertResearchResult,
    ProposalVisibility,
    TaskCreationRequest,
)
from app.contexts.business.proposal_management.application.use_cases import ProposalApplication
from app.contexts.business.proposal_management.domain import (
    Proposal,
    ProposalReview,
    ProposalStatus,
)


class _Repository:
    def __init__(self) -> None:
        self.proposals: dict[uuid.UUID, Proposal] = {}
        self.reviews: list[ProposalReview] = []

    async def add(self, proposal: Proposal) -> None:
        self.proposals[proposal.id] = copy.deepcopy(proposal)

    async def get(self, proposal_id: uuid.UUID) -> Proposal | None:
        proposal = self.proposals.get(proposal_id)
        return copy.deepcopy(proposal) if proposal is not None else None

    async def save(self, proposal: Proposal) -> None:
        self.proposals[proposal.id] = copy.deepcopy(proposal)

    async def delete(self, proposal_id: uuid.UUID) -> None:
        self.proposals.pop(proposal_id, None)

    async def list_proposals(
        self,
        *,
        status: str | None,
        limit: int,
        visibility: ProposalVisibility,
    ) -> list[Proposal]:
        proposals = list(self.proposals.values())
        if status is not None:
            proposals = [proposal for proposal in proposals if proposal.status.value == status]
        return copy.deepcopy(proposals[:limit])

    async def add_review(self, review: ProposalReview) -> None:
        self.reviews.append(copy.deepcopy(review))

    async def list_reviews(self, proposal_id: uuid.UUID) -> list[ProposalReview]:
        return copy.deepcopy(
            [review for review in self.reviews if review.proposal_id == proposal_id]
        )


class _UowTracker:
    def __init__(self) -> None:
        self.active = 0
        self.commits = 0
        self.rollbacks = 0


class _Uow:
    def __init__(self, repository: _Repository, tracker: _UowTracker) -> None:
        self.proposals = repository
        self._tracker = tracker
        self._committed = False
        self._snapshot: tuple[dict[uuid.UUID, Proposal], list[ProposalReview]] | None = None

    async def __aenter__(self) -> _Uow:
        self._tracker.active += 1
        self._committed = False
        self._snapshot = copy.deepcopy((self.proposals.proposals, self.proposals.reviews))
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object | None,
    ) -> None:
        try:
            if exc_type is not None or not self._committed:
                await self.rollback()
        finally:
            self._tracker.active -= 1

    async def commit(self) -> None:
        self._committed = True
        self._tracker.commits += 1

    async def rollback(self) -> None:
        if self._snapshot is not None:
            proposals, reviews = copy.deepcopy(self._snapshot)
            self.proposals.proposals = proposals
            self.proposals.reviews = reviews
        self._tracker.rollbacks += 1


class _ResearchPort:
    def __init__(self, tracker: _UowTracker) -> None:
        self._tracker = tracker
        self.calls: list[ExpertResearchRequest] = []

    async def find_expert(self, name: str) -> ExpertReference | None:
        assert self._tracker.active == 0
        return ExpertReference(id=uuid.uuid4(), name=name)

    async def research(
        self, expert: ExpertReference, request: ExpertResearchRequest
    ) -> ExpertResearchResult:
        assert expert.name == "会商AI专家"
        assert self._tracker.active == 0
        self.calls.append(request)
        return ExpertResearchResult(conclusion="建议上线，但需补充投入测算")


class _TaskPort:
    def __init__(self, tracker: _UowTracker, now: datetime) -> None:
        self._tracker = tracker
        self._now = now
        self.calls: list[TaskCreationRequest] = []

    async def create_task(self, request: TaskCreationRequest) -> TaskResult:
        assert self._tracker.active == 1
        self.calls.append(request)
        return TaskResult(
            id=uuid.uuid4(),
            title=request.title,
            task_type=request.task_type,
            priority=request.priority,
            status="created",
            creator_id=request.creator_id,
            assignee_agent_id=request.assignee_agent_id,
            parent_id=None,
            sla_hours=None,
            result_content=None,
            create_time=self._now,
        )


class _Policy:
    def visibility_for(self, viewer: ProposalViewer | None) -> ProposalVisibility:
        return ProposalVisibility(unrestricted=True)

    def ensure_visible(self, viewer: ProposalViewer | None, proposal: Proposal) -> None:
        return None


class _AuditPort:
    def __init__(self) -> None:
        self.records: list[AuditRequest] = []

    async def record(self, request: AuditRequest) -> None:
        self.records.append(request)


class _Clock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


class _Identifiers:
    def __init__(self) -> None:
        self._ids: deque[uuid.UUID] = deque(uuid.uuid4() for _ in range(20))

    def new_id(self) -> uuid.UUID:
        return self._ids.popleft()

    def new_proposal_code(self) -> str:
        return "PROP-TEST0001"


@pytest.fixture
def application() -> tuple[ProposalApplication, _Repository, _UowTracker, _AuditPort]:
    now = datetime(2026, 7, 23, 12, tzinfo=UTC)
    repository = _Repository()
    tracker = _UowTracker()
    audit = _AuditPort()
    app = ProposalApplication(
        uow_factory=lambda: _Uow(repository, tracker),
        research_port=_ResearchPort(tracker),
        task_port=_TaskPort(tracker, now),
        visibility_policy=_Policy(),
        audit_port=audit,
        clock=_Clock(now),
        identifiers=_Identifiers(),
    )
    return app, repository, tracker, audit


async def _create(app: ProposalApplication) -> ProposalResult:
    return await app.create(
        CreateProposalCommand(
            title="上线会员体系",
            background="留存低",
            plan="推出会员权益",
            creator_id=uuid.uuid4(),
        )
    )


async def test_create_commits_a_draft(
    application: tuple[ProposalApplication, _Repository, _UowTracker, _AuditPort],
) -> None:
    app, repository, tracker, _ = application

    result = await _create(app)

    assert result.status == "draft"
    assert result.code == "PROP-TEST0001"
    assert repository.proposals[result.id].status is ProposalStatus.DRAFT
    assert tracker.commits == 1


async def test_research_commits_pending_state_before_external_call(
    application: tuple[ProposalApplication, _Repository, _UowTracker, _AuditPort],
) -> None:
    app, repository, tracker, _ = application
    proposal = await _create(app)
    commits_before = tracker.commits

    review = await app.research(ResearchProposalCommand(proposal_id=proposal.id))

    assert review.review_type == "ai_research"
    assert review.decision is None
    assert repository.proposals[proposal.id].status is ProposalStatus.REVIEWED
    assert tracker.commits - commits_before == 2


async def test_human_review_and_conversion_use_ports_and_audit(
    application: tuple[ProposalApplication, _Repository, _UowTracker, _AuditPort],
) -> None:
    app, repository, _, audit = application
    proposal = await _create(app)
    await app.research(ResearchProposalCommand(proposal_id=proposal.id))

    approved = await app.review(
        ReviewProposalCommand(
            proposal_id=proposal.id,
            reviewer_id=uuid.uuid4(),
            conclusion="同意上线",
            decision="approve",
            actor_role="executive",
        )
    )
    task = await app.convert(
        ConvertProposalCommand(
            proposal_id=proposal.id,
            creator_id=uuid.uuid4(),
            actor_role="executive",
        )
    )

    assert approved.status == "approved"
    assert repository.proposals[proposal.id].converted_task_id == task.id
    assert [record.action for record in audit.records] == ["proposal.approve", "proposal.convert"]


async def test_edit_amends_draft_fields(
    application: tuple[ProposalApplication, _Repository, _UowTracker, _AuditPort],
) -> None:
    app, repository, _, _ = application
    creator = uuid.uuid4()
    proposal = await app.create(
        CreateProposalCommand(title="旧标题", background="b", plan="p", creator_id=creator)
    )

    edited = await app.edit(
        EditProposalCommand(
            proposal_id=proposal.id,
            actor_id=creator,
            title="新标题",
            background="b2",
            plan="p2",
            priority="high",
        )
    )

    assert edited.title == "新标题"
    assert repository.proposals[proposal.id].plan == "p2"
    assert repository.proposals[proposal.id].priority == "high"


async def test_edit_by_non_creator_masks_as_not_found(
    application: tuple[ProposalApplication, _Repository, _UowTracker, _AuditPort],
) -> None:
    app, _, _, _ = application
    proposal = await app.create(
        CreateProposalCommand(title="t", background="b", plan="p", creator_id=uuid.uuid4())
    )

    with pytest.raises(ProposalNotFound):
        await app.edit(
            EditProposalCommand(
                proposal_id=proposal.id,
                actor_id=uuid.uuid4(),
                title="x",
                background="b",
                plan="p",
            )
        )


async def test_edit_non_draft_rejected(
    application: tuple[ProposalApplication, _Repository, _UowTracker, _AuditPort],
) -> None:
    app, _, _, _ = application
    creator = uuid.uuid4()
    proposal = await app.create(
        CreateProposalCommand(title="t", background="b", plan="p", creator_id=creator)
    )
    await app.research(ResearchProposalCommand(proposal_id=proposal.id))

    with pytest.raises(ProposalError, match="不可编辑/删除"):
        await app.edit(
            EditProposalCommand(
                proposal_id=proposal.id,
                actor_id=creator,
                title="x",
                background="b",
                plan="p",
            )
        )


async def test_delete_removes_own_draft(
    application: tuple[ProposalApplication, _Repository, _UowTracker, _AuditPort],
) -> None:
    app, repository, _, _ = application
    creator = uuid.uuid4()
    proposal = await app.create(
        CreateProposalCommand(title="t", background="b", plan="p", creator_id=creator)
    )

    await app.delete(DeleteProposalCommand(proposal_id=proposal.id, actor_id=creator))

    assert proposal.id not in repository.proposals
