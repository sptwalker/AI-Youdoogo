"""工作桌面对话单测：专属助理 + 持久历史 + 10天归档 + 圆桌多AI（不发真实请求）。"""

import uuid
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.contexts.business.assistant_conversations.application.contracts import (
    Principal,
    SendMessageCommand,
)
from app.contexts.business.assistant_conversations.entrypoints import (
    operations as assistant_conversations,
)
from app.contexts.foundations.knowledge.knowledge_indexing import public as knowledge_indexing
from app.contexts.foundations.knowledge.organizational_memory import (
    public as organizational_memory,
)
from app.contexts.shared_kernel import ApplicationError
from app.core.sse import Event
from app.models import Base
from app.models.agent import AgentRole, AgentTaskRecord
from app.models.desktop import DesktopMessage
from app.models.knowledge import SCOPE_PERSONAL, KnowledgeBase
from app.models.system import SysUser
from app.services import agent_role_service

AgentStream = Callable[..., AsyncIterator[str | AgentTaskRecord]]


@pytest.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


async def _user(db: AsyncSession, username: str = "alice", real_name: str = "爱丽丝") -> SysUser:
    u = SysUser(username=username, password_hash="x", real_name=real_name, role_code="member")
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


def _principal(user: SysUser) -> Principal:
    return Principal(
        id=user.id,
        display_name=user.real_name or user.username,
        department_id=user.department_id,
    )


def _fake_run_agent_stream(calls: list[str]):
    """记录每次 run_agent_stream 的 user_message，流式返回递增回复（末项为留痕记录）。"""

    async def _run(db: AsyncSession, role: AgentRole, **kw: Any):
        calls.append(kw["user_message"])
        n = len(calls)
        yield "re"
        yield f"ply{n}"
        yield AgentTaskRecord(
            id=uuid.uuid4(),
            agent_role_id=role.id,
            task_type="desktop_chat",
            output_content=f"reply{n}",
            status="success",
        )

    return _run


async def _send_all(
    db: AsyncSession,
    user: SysUser,
    message: str,
    add_agent_ids: list[uuid.UUID],
    *,
    agent_stream: AgentStream | None = None,
    agent_runner: Any = None,
) -> tuple[list[dict[str, Any]], list[Event]]:
    """drain send_stream：返回 (message_end 消息列表, 全部事件)。"""
    events = [
        event
        async for event in assistant_conversations.send_message_stream(
            db,
            SendMessageCommand(
                principal=_principal(user),
                message=message,
                add_agent_ids=tuple(add_agent_ids),
            ),
            agent_stream=agent_stream,
            agent_runner=agent_runner,
        )
    ]
    return [d for name, d in events if name == "message_end"], events


async def test_assistant_idempotent_and_personal_kb(db: AsyncSession) -> None:
    """get_or_create_assistant 幂等 + 建 personal KB。"""
    u = await _user(db)
    a1 = await assistant_conversations.get_or_create_assistant(db, _principal(u))
    a2 = await assistant_conversations.get_or_create_assistant(db, _principal(u))
    assert a1.id == a2.id
    assert a1.owner_user_id == u.id
    kb = (
        await db.execute(
            select(KnowledgeBase).where(
                KnowledgeBase.scope == SCOPE_PERSONAL,
                KnowledgeBase.owner_agent_id == a1.id,
            )
        )
    ).scalar_one_or_none()
    assert kb is not None


async def test_assistant_name_collision_suffix(db: AsyncSession) -> None:
    """两个同名真人 → 助理撞名自动加后缀，均建成。"""
    u1 = await _user(db, "u1", "张伟")
    u2 = await _user(db, "u2", "张伟")
    a1 = await assistant_conversations.get_or_create_assistant(db, _principal(u1))
    a2 = await assistant_conversations.get_or_create_assistant(db, _principal(u2))
    assert a1.id != a2.id
    assert a1.name != a2.name


async def test_list_agent_roles_excludes_assistant(db: AsyncSession) -> None:
    """组织智能体列表不含真人专属助理。"""
    u = await _user(db)
    await assistant_conversations.get_or_create_assistant(db, _principal(u))
    await agent_role_service.create_agent_role(db, name="运营总监", prompt_template="x")
    names = [r.name for r in await agent_role_service.list_agent_roles(db)]
    assert "运营总监" in names
    assert all("的助理" not in n for n in names)


async def test_send_roundtable_order_and_context(db: AsyncSession) -> None:
    """圆桌：助理 + 1 个被加入AI，2 轮 → 5 条消息；后发言者能看到先发言者内容；delta 流式送达。"""
    calls: list[str] = []
    u = await _user(db)
    expert = await agent_role_service.create_agent_role(db, name="专家A", prompt_template="x")

    msgs, events = await _send_all(
        db,
        u,
        "帮我分析一下",
        [expert.id],
        agent_stream=_fake_run_agent_stream(calls),
    )
    # 1 user + 2 参与者 × 2 轮 = 5
    assert len(msgs) == 5
    assert msgs[0]["speaker_type"] == "user"
    ai_names = [m["speaker_name"] for m in msgs[1:]]
    assert "专家A" in ai_names  # 被加入的AI确实发言
    # 第二个发言者的 prompt 应包含第一个发言者的回复（圆桌可见）
    assert "reply1" in calls[1]
    # 流式协议：4 个 AI 发言 → 各 1 个 message_start + 2 个 delta
    names = [n for n, _ in events]
    assert names.count("message_start") == 4
    assert names.count("delta") == 8
    assert names[0] == "message_end"  # 用户消息回显在最前


async def test_send_rejects_more_than_two_added(db: AsyncSession) -> None:
    """最多再加 2 个 AI。"""
    u = await _user(db)
    ids = [uuid.uuid4() for _ in range(3)]
    with pytest.raises(ApplicationError, match="最多"):
        await _send_all(db, u, "hi", ids)


async def test_send_consult_directive_emits_extra_message(
    db: AsyncSession,
) -> None:
    """协作原语集成：助理产出含【咨询 @X】→ 流中出现被咨询 AI 的独立消息。"""
    async def _stream_with_directive(db_: AsyncSession, role: AgentRole, **kw: Any):
        yield "我先咨询一下。"
        yield AgentTaskRecord(
            id=uuid.uuid4(),
            agent_role_id=role.id,
            task_type="desktop_chat",
            output_content="我先咨询一下。\n【咨询 @财务总监】预算多少？",
            status="success",
        )

    async def _consult_run(db_: AsyncSession, role: AgentRole, **kw: Any) -> AgentTaskRecord:
        return AgentTaskRecord(
            id=uuid.uuid4(),
            agent_role_id=role.id,
            task_type="agent_consult",
            output_content="预算上限100万。",
            status="success",
        )

    u = await _user(db)
    await agent_role_service.create_agent_role(db, name="财务总监", prompt_template="x")

    msgs, _ = await _send_all(
        db,
        u,
        "预算是多少",
        [],
        agent_stream=_stream_with_directive,
        agent_runner=_consult_run,
    )
    # user + 助理（1轮1人）+ 被咨询AI答复 = 3
    assert len(msgs) == 3
    assert msgs[2]["speaker_name"] == "财务总监"
    assert msgs[2]["content"] == "预算上限100万。"


async def _add_msg(db: AsyncSession, user_id: uuid.UUID, content: str, days_ago: int) -> None:
    db.add(
        DesktopMessage(
            owner_user_id=user_id,
            speaker_type="user",
            speaker_name="爱丽丝",
            content=content,
            create_time=datetime.now(UTC) - timedelta(days=days_ago),
        )
    )
    await db.commit()


async def test_archive_old_moves_and_deletes(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """>10天旧消息 ingest 后硬删；≤10天保留。"""
    ingested: list[dict[str, Any]] = []

    async def _no_distill(*args: Any, **kwargs: Any) -> None:
        return None

    async def _fake_ingest(db: AsyncSession, command: Any) -> None:
        ingested.append({"title": command.title, "text": command.text})

    monkeypatch.setattr(organizational_memory, "distill_conversation", _no_distill)
    monkeypatch.setattr(knowledge_indexing, "index_text", _fake_ingest)
    u = await _user(db)
    await assistant_conversations.get_or_create_assistant(db, _principal(u))
    await _add_msg(db, u.id, "很久以前", days_ago=11)
    await _add_msg(db, u.id, "最近", days_ago=1)

    n = await assistant_conversations.archive_old(db, _principal(u), days=10)
    assert n == 1
    assert len(ingested) == 1 and "很久以前" in ingested[0]["text"]
    remaining = list(
        (
            await db.execute(select(DesktopMessage).where(DesktopMessage.owner_user_id == u.id))
        ).scalars()
    )
    assert [m.content for m in remaining] == ["最近"]


async def test_archive_old_keeps_on_ingest_failure(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """归档入库失败 → 不删消息（下次重试）。"""

    async def _no_distill(*args: Any, **kwargs: Any) -> None:
        return None

    async def _boom(db: AsyncSession, command: Any) -> None:
        raise RuntimeError("embedding down")

    monkeypatch.setattr(organizational_memory, "distill_conversation", _no_distill)
    monkeypatch.setattr(knowledge_indexing, "index_text", _boom)
    u = await _user(db)
    await assistant_conversations.get_or_create_assistant(db, _principal(u))
    await _add_msg(db, u.id, "很久以前", days_ago=11)

    n = await assistant_conversations.archive_old(db, _principal(u), days=10)
    assert n == 0
    remaining = list(
        (
            await db.execute(select(DesktopMessage).where(DesktopMessage.owner_user_id == u.id))
        ).scalars()
    )
    assert len(remaining) == 1  # 未删，保留重试
