"""工作桌面对话单测：专属助理 + 持久历史 + 10天归档 + 圆桌多AI（不发真实请求）。"""

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.exceptions import AppError
from app.models import Base
from app.models.agent import AgentRole
from app.models.desktop import DesktopMessage
from app.models.knowledge import SCOPE_PERSONAL, KnowledgeBase
from app.models.system import SysUser
from app.services import agent_role_service
from app.services import desktop_chat_service as svc


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


def _fake_run_agent(calls: list[str]):
    """记录每次 run_agent 的 user_message，返回递增回复。"""

    async def _run(db: AsyncSession, role: AgentRole, **kw: Any) -> SimpleNamespace:
        calls.append(kw["user_message"])
        return SimpleNamespace(
            output_content=f"reply{len(calls)}", error_msg=None, status="success"
        )

    return _run


async def test_assistant_idempotent_and_personal_kb(db: AsyncSession) -> None:
    """get_or_create_assistant 幂等 + 建 personal KB。"""
    u = await _user(db)
    a1 = await svc.get_or_create_assistant(db, u)
    a2 = await svc.get_or_create_assistant(db, u)
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
    a1 = await svc.get_or_create_assistant(db, u1)
    a2 = await svc.get_or_create_assistant(db, u2)
    assert a1.id != a2.id
    assert a1.name != a2.name


async def test_list_agent_roles_excludes_assistant(db: AsyncSession) -> None:
    """组织智能体列表不含真人专属助理。"""
    u = await _user(db)
    await svc.get_or_create_assistant(db, u)
    await agent_role_service.create_agent_role(db, name="运营总监", prompt_template="x")
    names = [r.name for r in await agent_role_service.list_agent_roles(db)]
    assert "运营总监" in names
    assert all("的助理" not in n for n in names)


async def test_send_roundtable_order_and_context(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """圆桌：助理 + 1 个被加入AI，2 轮 → 5 条消息；后发言者能看到先发言者内容。"""
    calls: list[str] = []
    monkeypatch.setattr(svc, "run_agent", _fake_run_agent(calls))
    u = await _user(db)
    expert = await agent_role_service.create_agent_role(db, name="专家A", prompt_template="x")

    msgs = await svc.send(db, u, "帮我分析一下", [expert.id])
    # 1 user + 2 参与者 × 2 轮 = 5
    assert len(msgs) == 5
    assert msgs[0]["speaker_type"] == "user"
    ai_names = [m["speaker_name"] for m in msgs[1:]]
    assert "专家A" in ai_names  # 被加入的AI确实发言
    # 第二个发言者的 prompt 应包含第一个发言者的回复（圆桌可见）
    assert "reply1" in calls[1]


async def test_send_rejects_more_than_two_added(db: AsyncSession) -> None:
    """最多再加 2 个 AI。"""
    u = await _user(db)
    ids = [uuid.uuid4() for _ in range(3)]
    with pytest.raises(AppError, match="最多"):
        await svc.send(db, u, "hi", ids)


async def _add_msg(db: AsyncSession, user_id: uuid.UUID, content: str, days_ago: int) -> None:
    db.add(
        DesktopMessage(
            owner_user_id=user_id, speaker_type="user", speaker_name="爱丽丝",
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

    async def _fake_ingest(db: AsyncSession, **kw: Any) -> SimpleNamespace:
        ingested.append(kw)
        return SimpleNamespace(id=uuid.uuid4())

    monkeypatch.setattr(svc, "ingest_text", _fake_ingest)
    u = await _user(db)
    await svc.get_or_create_assistant(db, u)
    await _add_msg(db, u.id, "很久以前", days_ago=11)
    await _add_msg(db, u.id, "最近", days_ago=1)

    n = await svc.archive_old(db, u, days=10)
    assert n == 1
    assert len(ingested) == 1 and "很久以前" in ingested[0]["text"]
    remaining = list(
        (await db.execute(select(DesktopMessage).where(DesktopMessage.owner_user_id == u.id)))
        .scalars()
    )
    assert [m.content for m in remaining] == ["最近"]


async def test_archive_old_keeps_on_ingest_failure(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """归档入库失败 → 不删消息（下次重试）。"""

    async def _boom(db: AsyncSession, **kw: Any) -> None:
        raise RuntimeError("embedding down")

    monkeypatch.setattr(svc, "ingest_text", _boom)
    u = await _user(db)
    await svc.get_or_create_assistant(db, u)
    await _add_msg(db, u.id, "很久以前", days_ago=11)

    n = await svc.archive_old(db, u, days=10)
    assert n == 0
    remaining = list(
        (await db.execute(select(DesktopMessage).where(DesktopMessage.owner_user_id == u.id)))
        .scalars()
    )
    assert len(remaining) == 1  # 未删，保留重试
