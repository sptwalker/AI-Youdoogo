"""会议会商全流程单测（假模型 + 内存 SQLite）。"""

import uuid
from collections.abc import AsyncGenerator, AsyncIterator

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.agents import base
from app.core.exceptions import AppError
from app.models import Base
from app.models.agent import AgentRole
from app.models.meeting import CLOSED, IN_PROGRESS
from app.models.system import SysUser
from app.services import meeting_service


class _FakeLLM:
    def __init__(self, text: str) -> None:
        self._text = text

    async def ainvoke(self, messages: list, **kwargs: object) -> AIMessage:
        return AIMessage(content=self._text)

    async def astream(self, messages: list, **kwargs: object) -> AsyncIterator[AIMessageChunk]:
        # 逐字吐（验证 delta 逐段送达）
        for ch in self._text:
            yield AIMessageChunk(content=ch)


async def _ai_speak(session: AsyncSession, meeting_id: uuid.UUID, topic: str) -> dict:
    """drain ai_expert_speak_stream，返回 message_end 落库消息。"""
    events = [
        e async for e in meeting_service.ai_expert_speak_stream(session, meeting_id, topic=topic)
    ]
    names = [n for n, _ in events]
    assert names[0] == "message_start" and names[-1] == "message_end"
    assert names.count("delta") > 1  # 确实逐段流出
    return events[-1][1]


@pytest.fixture
async def ctx() -> AsyncGenerator[tuple[AsyncSession, uuid.UUID], None]:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        user = SysUser(username="ceo", password_hash="x", real_name="老板", role_code="executive")
        expert = AgentRole(
            name=meeting_service.EXPERT_NAME, prompt_template="你是会商AI专家。",
            model_role="reasoning",
        )
        session.add_all([user, expert])
        await session.commit()
        yield session, user.id
    await engine.dispose()


async def _open_meeting(session: AsyncSession, uid: uuid.UUID):
    m = await meeting_service.create_meeting(session, title="Q3 决策会", creator_id=uid)
    return await meeting_service.set_status(session, m.id, IN_PROGRESS)


async def test_full_meeting_flow(ctx, monkeypatch: pytest.MonkeyPatch) -> None:
    session, uid = ctx
    monkeypatch.setattr(
        base, "get_llm_for_role", lambda *a, **k: _FakeLLM("approve\n方案可行，收益明确。")
    )
    m = await _open_meeting(session, uid)

    await meeting_service.add_discussion(
        session, m.id, speaker_id=uid, speaker_name="老板", content="我倾向上线会员体系。"
    )
    ai_d = await _ai_speak(session, m.id, "是否上线会员体系")
    assert ai_d["speaker_type"] == "ai" and "可行" in ai_d["content"]

    await meeting_service.cast_vote(
        session, m.id, subject="会员体系", voter_type="human", voter_id=uid, choice="approve"
    )
    ai_v = await meeting_service.ai_expert_vote(session, m.id, subject="会员体系")
    assert ai_v.voter_type == "ai" and ai_v.choice == "approve"

    tally = await meeting_service.tally_votes(session, m.id, "会员体系")
    assert tally["human"]["approve"] == 1 and tally["ai"]["approve"] == 1
    assert tally["human_passed"] is True

    m2 = await meeting_service.generate_minutes(session, m.id)
    assert m2.summary and "可行" in m2.summary

    r = await meeting_service.create_resolution(session, m.id, content="批准上线会员体系")
    assert r.is_confirmed is False


async def test_resolution_requires_human_confirm(ctx, monkeypatch: pytest.MonkeyPatch) -> None:
    """红线：未确认决议不能转任务卡；确认后可转。"""
    session, uid = ctx
    m = await _open_meeting(session, uid)
    r = await meeting_service.create_resolution(session, m.id, content="决议X")

    with pytest.raises(AppError, match="真人确认"):
        await meeting_service.resolution_to_task(session, r.id, creator_id=uid)

    confirmed = await meeting_service.confirm_resolution(session, r.id, confirmed_by=uid)
    assert confirmed.is_confirmed is True and confirmed.confirmed_by == uid

    task = await meeting_service.resolution_to_task(session, r.id, creator_id=uid)
    assert task.task_type == "resolution_execution"
    with pytest.raises(AppError, match="已转过"):
        await meeting_service.resolution_to_task(session, r.id, creator_id=uid)


async def test_discuss_requires_in_progress(ctx) -> None:
    session, uid = ctx
    m = await meeting_service.create_meeting(session, title="M", creator_id=uid)  # scheduled
    with pytest.raises(AppError, match="需先开始"):
        await meeting_service.add_discussion(
            session, m.id, speaker_id=uid, speaker_name="x", content="hi"
        )


async def test_illegal_status_transition(ctx) -> None:
    session, uid = ctx
    m = await _open_meeting(session, uid)
    await meeting_service.set_status(session, m.id, CLOSED)
    with pytest.raises(AppError, match="非法会议状态流转"):
        await meeting_service.set_status(session, m.id, IN_PROGRESS)


async def test_minutes_needs_discussion(ctx) -> None:
    session, uid = ctx
    m = await _open_meeting(session, uid)
    with pytest.raises(AppError, match="无发言"):
        await meeting_service.generate_minutes(session, m.id)


def test_parse_choice_rejects_negation() -> None:
    """AI 参考票解析：首行开头匹配，否定句不误判（红线：AI票仅参考也不能反向）。"""
    p = meeting_service._parse_choice
    assert p("approve\n方案可行") == "approve"
    assert p("**reject** 风险高") == "reject"
    assert p("我不建议 approve，风险太大") == "abstain"  # 否定句不再误判为 approve
    assert p("") == "abstain"
