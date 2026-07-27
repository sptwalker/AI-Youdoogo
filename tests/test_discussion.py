"""协作空间 F3' 单测：@Agent 五件套护栏 + 升格 + 部门自动建频道（假模型 + 内存 SQLite）。"""

import uuid
from collections.abc import AsyncGenerator, AsyncIterator
from typing import Any

import pytest
from langchain_core.messages import AIMessageChunk
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.contexts.foundations.model_gateway import public as _mg_public
from app.models import Base
from app.models.agent import AgentRole
from app.models.discussion import DiscussionChannel, DiscussionMessage
from app.models.proposal import ProposalCard
from app.models.system import COMPANY, SysDepartment
from app.services import discussion_service, org_service


class _FakeLLM:
    async def astream(self, messages: list, **kwargs: Any) -> AsyncIterator[AIMessageChunk]:
        yield AIMessageChunk(content="AI 顾问", response_metadata={"model_name": "fake"})
        yield AIMessageChunk(content="参考意见。")


async def _post(s: AsyncSession, channel_id: uuid.UUID, **kw: Any) -> dict[str, Any]:
    """drain post_message_stream，还原成旧 {human, ai} 形状便于断言。"""
    events = [e async for e in discussion_service.post_message_stream(s, channel_id, **kw)]
    ends = [d for name, d in events if name == "message_end"]
    return {"human": ends[0], "ai": ends[1:]}


Ctx = tuple[AsyncSession, DiscussionChannel, list[AgentRole]]


@pytest.fixture(autouse=True)
def _stub_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_mg_public, "get_llm_for_role", lambda *a, **k: _FakeLLM())


@pytest.fixture
async def ctx() -> AsyncGenerator[tuple[AsyncSession, DiscussionChannel, list[AgentRole]], None]:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        channel = DiscussionChannel(name="测试频道")
        agents = [
            AgentRole(name=f"顾问{i}", prompt_template=f"你是顾问{i}。", model_role="daily")
            for i in range(5)
        ]
        s.add_all([channel, *agents])
        await s.commit()
        for a in agents:
            await s.refresh(a)
        await s.refresh(channel)
        yield s, channel, agents
    await engine.dispose()


async def _ai_count(s: AsyncSession, channel_id: uuid.UUID) -> int:
    return (
        await s.execute(
            select(func.count()).select_from(DiscussionMessage).where(
                DiscussionMessage.channel_id == channel_id,
                DiscussionMessage.speaker_type == "ai",
            )
        )
    ).scalar_one()


async def test_no_mention_no_ai(ctx: Ctx) -> None:
    """护栏1：无 @ 不调 AI。"""
    s, channel, _ = ctx
    result = await _post(
        s, channel.id, speaker_id=uuid.uuid4(), speaker_name="老板", content="随便聊聊",
        mentioned_agent_ids=[],
    )
    assert result["ai"] == []
    assert await _ai_count(s, channel.id) == 0


async def test_mention_triggers_one_each(
    ctx: Ctx,
) -> None:
    """护栏2：@2 个 → 2 条 AI 回复，各一次。"""
    s, channel, agents = ctx
    result = await _post(
        s, channel.id, speaker_id=uuid.uuid4(), speaker_name="老板", content="看法？",
        mentioned_agent_ids=[agents[0].id, agents[1].id],
    )
    assert len(result["ai"]) == 2
    assert await _ai_count(s, channel.id) == 2


async def test_dedup_same_agent(
    ctx: Ctx,
) -> None:
    """护栏3：@ 同一 agent×5 去重 → 只回一次。"""
    s, channel, agents = ctx
    result = await _post(
        s, channel.id, speaker_id=uuid.uuid4(), speaker_name="老板", content="看法？",
        mentioned_agent_ids=[agents[0].id] * 5,
    )
    assert len(result["ai"]) == 1


async def test_fanout_capped_at_three(
    ctx: Ctx,
) -> None:
    """护栏3：@5 个不同 agent → 截到 3。"""
    s, channel, agents = ctx
    result = await _post(
        s, channel.id, speaker_id=uuid.uuid4(), speaker_name="老板", content="看法？",
        mentioned_agent_ids=[a.id for a in agents],
    )
    assert len(result["ai"]) == discussion_service.MAX_FANOUT == 3


async def test_promote_to_proposal(
    ctx: Ctx,
) -> None:
    """升格：一条消息 → 提案，消息回填 ref_type/ref_id。"""
    s, channel, _ = ctx
    posted = await _post(
        s, channel.id, speaker_id=uuid.uuid4(), speaker_name="老板",
        content="建议做个新活动方案", mentioned_agent_ids=[],
    )
    msg_id = uuid.UUID(posted["human"]["id"])
    ref = await discussion_service.promote_message(
        s, msg_id, target="proposal", creator_id=uuid.uuid4()
    )
    assert ref["ref_type"] == "proposal"
    msg = await s.get(DiscussionMessage, msg_id)
    assert msg is not None and msg.ref_type == "proposal"
    assert (await s.get(ProposalCard, uuid.UUID(ref["ref_id"]))) is not None
    # 已升格再升格被拒
    with pytest.raises(Exception, match="已升格"):
        await discussion_service.promote_message(s, msg_id, target="task", creator_id=uuid.uuid4())


async def test_create_node_auto_channel(
    ctx: Ctx,
) -> None:
    """部门自动建频道：新建部门 → 生成 1 个默认频道。"""
    s, _, _ = ctx
    root = SysDepartment(name="创想悦动", code="company", node_type=COMPANY, level=0, path="")
    s.add(root)
    await s.commit()
    await s.refresh(root)
    root.path = f"/{root.id}/"
    await s.commit()

    node = await org_service.create_node(s, name="平台运营部", parent_id=root.id)
    n = (
        await s.execute(
            select(func.count()).select_from(DiscussionChannel).where(
                DiscussionChannel.department_id == node.id
            )
        )
    ).scalar_one()
    assert n == 1
