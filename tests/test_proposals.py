"""提案卡全流程单测：创建→AI预研→真人评审→转任务卡（假模型 + 内存 SQLite）。"""

import uuid
from collections.abc import AsyncGenerator
from typing import Any

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.contexts.business.proposal_management import (
    InvalidProposalDecision,
    ProposalAlreadyConverted,
    ProposalNotApproved,
    ProposalNotFound,
    ProposalResearchNotAllowed,
    ProposalReviewNotAllowed,
)
from app.contexts.business.proposal_management.application.use_cases import EXPERT_NAME
from app.contexts.business.proposal_management.entrypoints import (
    operations as proposal_service,
)
from app.contexts.foundations.model_gateway import public as model_gateway
from app.models import Base
from app.models.agent import AgentRole
from app.models.proposal import APPROVED, REJECTED, RESEARCHING, REVIEWED, ProposalCard
from app.models.system import SysUser


class _FakeLLM:
    def __init__(
        self,
        observer_factory: async_sessionmaker[AsyncSession] | None = None,
        proposal_id: uuid.UUID | None = None,
    ) -> None:
        self._observer_factory = observer_factory
        self._proposal_id = proposal_id
        self.observed_statuses: list[str] = []

    async def ainvoke(self, messages: list, **kwargs: object) -> AIMessage:
        if self._observer_factory is not None and self._proposal_id is not None:
            async with self._observer_factory() as observer:
                proposal = await observer.get(ProposalCard, self._proposal_id)
                assert proposal is not None
                self.observed_statuses.append(proposal.status)
        return AIMessage(content="预研结论：可行性中等，主要风险为投入产出比。")


@pytest.fixture
async def ctx() -> AsyncGenerator[
    tuple[AsyncSession, async_sessionmaker[AsyncSession], uuid.UUID], None
]:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        user = SysUser(username="boss", password_hash="x", role_code="executive")
        expert = AgentRole(
            name=EXPERT_NAME,
            prompt_template="你是会商AI专家。",
            model_role="reasoning",
        )
        session.add_all([user, expert])
        await session.commit()
        yield session, factory, user.id
    await engine.dispose()


async def _new_proposal(session: AsyncSession, uid: uuid.UUID) -> Any:
    return await proposal_service.create_proposal(
        session, title="上线会员体系", background="留存低", plan="推出会员权益", creator_id=uid
    )


async def test_full_pipeline_approve_and_convert(
    ctx: tuple[AsyncSession, async_sessionmaker[AsyncSession], uuid.UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, _, uid = ctx
    monkeypatch.setattr(model_gateway, "get_llm_for_role", lambda *a, **k: _FakeLLM())
    p = await _new_proposal(session, uid)
    assert p.code.startswith("PROP-")

    review = await proposal_service.run_ai_research(session, p.id)
    assert review.review_type == "ai_research" and "预研结论" in review.conclusion
    assert (await proposal_service.get_proposal(session, p.id)).status == REVIEWED

    approved = await proposal_service.human_review(
        session, p.id, reviewer_id=uid, conclusion="同意上线", decision="approve"
    )
    assert approved.status == APPROVED

    task = await proposal_service.convert_to_task(session, p.id, creator_id=uid)
    assert task.task_type == "proposal_execution"
    assert (await proposal_service.get_proposal(session, p.id)).converted_task_id == task.id


async def test_reject_blocks_convert(
    ctx: tuple[AsyncSession, async_sessionmaker[AsyncSession], uuid.UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, _, uid = ctx
    monkeypatch.setattr(model_gateway, "get_llm_for_role", lambda *a, **k: _FakeLLM())
    p = await _new_proposal(session, uid)
    await proposal_service.run_ai_research(session, p.id)
    rejected = await proposal_service.human_review(
        session, p.id, reviewer_id=uid, conclusion="暂缓", decision="reject"
    )
    assert rejected.status == REJECTED
    with pytest.raises(ProposalNotApproved, match="已通过"):
        await proposal_service.convert_to_task(session, p.id, creator_id=uid)


async def test_cannot_review_before_research(
    ctx: tuple[AsyncSession, async_sessionmaker[AsyncSession], uuid.UUID],
) -> None:
    """红线：未完成预研（仍 draft）不能直接评审通过。"""
    session, _, uid = ctx
    p = await _new_proposal(session, uid)
    with pytest.raises(ProposalReviewNotAllowed, match="不可评审"):
        await proposal_service.human_review(
            session, p.id, reviewer_id=uid, conclusion="x", decision="approve"
        )


async def test_convert_requires_approved(
    ctx: tuple[AsyncSession, async_sessionmaker[AsyncSession], uuid.UUID],
) -> None:
    session, _, uid = ctx
    p = await _new_proposal(session, uid)
    with pytest.raises(ProposalNotApproved, match="已通过"):
        await proposal_service.convert_to_task(session, p.id, creator_id=uid)


async def test_researching_state_is_visible_before_external_ai_call(
    ctx: tuple[AsyncSession, async_sessionmaker[AsyncSession], uuid.UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, factory, uid = ctx
    proposal = await _new_proposal(session, uid)
    fake_llm = _FakeLLM(factory, proposal.id)
    monkeypatch.setattr(
        model_gateway, "get_llm_for_role", lambda *args, **kwargs: fake_llm
    )

    await proposal_service.run_ai_research(session, proposal.id, operator_id=uid)

    assert fake_llm.observed_statuses
    assert set(fake_llm.observed_statuses) == {RESEARCHING}


async def test_proposal_failure_semantics_are_stable(
    ctx: tuple[AsyncSession, async_sessionmaker[AsyncSession], uuid.UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, _, uid = ctx
    with pytest.raises(ProposalNotFound, match="提案不存在"):
        await proposal_service.get_proposal(session, uuid.uuid4())

    proposal = await _new_proposal(session, uid)
    with pytest.raises(InvalidProposalDecision, match="approve / reject"):
        await proposal_service.human_review(
            session,
            proposal.id,
            reviewer_id=uid,
            conclusion="无效决议",
            decision="abstain",
        )

    monkeypatch.setattr(
        model_gateway, "get_llm_for_role", lambda *args, **kwargs: _FakeLLM()
    )
    await proposal_service.run_ai_research(session, proposal.id)
    await proposal_service.human_review(
        session,
        proposal.id,
        reviewer_id=uid,
        conclusion="同意",
        decision="approve",
    )
    with pytest.raises(ProposalResearchNotAllowed, match="不可再预研"):
        await proposal_service.run_ai_research(session, proposal.id)

    await proposal_service.convert_to_task(session, proposal.id, creator_id=uid)
    with pytest.raises(ProposalAlreadyConverted, match="已转过任务卡"):
        await proposal_service.convert_to_task(session, proposal.id, creator_id=uid)
