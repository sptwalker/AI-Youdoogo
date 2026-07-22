"""提案卡全流程单测：创建→AI预研→真人评审→转任务卡（假模型 + 内存 SQLite）。"""

import uuid
from collections.abc import AsyncGenerator

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.agents import base
from app.contexts.business.proposal_management import (
    ProposalNotApproved,
    ProposalReviewNotAllowed,
)
from app.models import Base
from app.models.agent import AgentRole
from app.models.proposal import APPROVED, REJECTED, REVIEWED
from app.models.system import SysUser
from app.services import proposal_service


class _FakeLLM:
    async def ainvoke(self, messages: list, **kwargs: object) -> AIMessage:
        return AIMessage(content="预研结论：可行性中等，主要风险为投入产出比。")


@pytest.fixture
async def ctx() -> AsyncGenerator[tuple[AsyncSession, uuid.UUID], None]:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        user = SysUser(username="boss", password_hash="x", role_code="executive")
        expert = AgentRole(
            name=proposal_service.EXPERT_NAME,
            prompt_template="你是会商AI专家。",
            model_role="reasoning",
        )
        session.add_all([user, expert])
        await session.commit()
        yield session, user.id
    await engine.dispose()


async def _new_proposal(session: AsyncSession, uid: uuid.UUID):
    return await proposal_service.create_proposal(
        session, title="上线会员体系", background="留存低", plan="推出会员权益", creator_id=uid
    )


async def test_full_pipeline_approve_and_convert(
    ctx: tuple[AsyncSession, uuid.UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    session, uid = ctx
    monkeypatch.setattr(base, "get_llm_for_role", lambda *a, **k: _FakeLLM())
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
    ctx: tuple[AsyncSession, uuid.UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    session, uid = ctx
    monkeypatch.setattr(base, "get_llm_for_role", lambda *a, **k: _FakeLLM())
    p = await _new_proposal(session, uid)
    await proposal_service.run_ai_research(session, p.id)
    rejected = await proposal_service.human_review(
        session, p.id, reviewer_id=uid, conclusion="暂缓", decision="reject"
    )
    assert rejected.status == REJECTED
    with pytest.raises(ProposalNotApproved, match="已通过"):
        await proposal_service.convert_to_task(session, p.id, creator_id=uid)


async def test_cannot_review_before_research(ctx: tuple[AsyncSession, uuid.UUID]) -> None:
    """红线：未完成预研（仍 draft）不能直接评审通过。"""
    session, uid = ctx
    p = await _new_proposal(session, uid)
    with pytest.raises(ProposalReviewNotAllowed, match="不可评审"):
        await proposal_service.human_review(
            session, p.id, reviewer_id=uid, conclusion="x", decision="approve"
        )


async def test_convert_requires_approved(ctx: tuple[AsyncSession, uuid.UUID]) -> None:
    session, uid = ctx
    p = await _new_proposal(session, uid)
    with pytest.raises(ProposalNotApproved, match="已通过"):
        await proposal_service.convert_to_task(session, p.id, creator_id=uid)
