"""结构化记忆单测（H3.2，docs/16）:提炼输入构造 + 提炼成功/失败兜底 + 归档改存提炼版。"""

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.contexts.business.assistant_conversations.application.contracts import Principal
from app.contexts.business.assistant_conversations.entrypoints import (
    operations as assistant_conversations,
)
from app.contexts.foundations.knowledge.knowledge_indexing import public as knowledge_indexing
from app.contexts.foundations.knowledge.organizational_memory import (
    public as organizational_memory,
)
from app.contexts.foundations.knowledge.organizational_memory.contracts import (
    DistillConversationCommand,
    MemoryDraft,
)
from app.contexts.foundations.knowledge.organizational_memory.domain.policies import (
    build_distillation_input,
)
from app.models import Base
from app.models.desktop import SPEAKER_USER, DesktopMessage
from app.models.system import SysUser


@pytest.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


# ── 纯函数 + 提炼 ───────────────────────────────────────
def test_build_distill_input_truncates() -> None:
    out = build_distillation_input("对" * 10000)
    assert out.startswith("请提炼") and len(out) < 8100


async def test_distill_empty_returns_none(db: AsyncSession) -> None:
    assert (
        await organizational_memory.distill_conversation(
            db,
            DistillConversationCommand(transcript="   "),
            llm_factory=lambda *args, **kwargs: None,
        )
        is None
    )


async def test_distill_success(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM 返回结构化记忆 → 原样返回（去空白）。"""

    class _Reply:
        content = "## 摘要\n谈了运营数据。\n## 涉及实体\n盒子A5"
        response_metadata: dict[str, Any] = {}
        usage_metadata: dict[str, Any] = {}

    class _LLM:
        async def ainvoke(self, *a: Any, **k: Any) -> Any:
            return _Reply()

    draft = await organizational_memory.distill_conversation(
        db,
        DistillConversationCommand(transcript="用户：查下A5\n助理：好的"),
        llm_factory=lambda *args, **kwargs: _LLM(),
    )
    assert draft is not None and "摘要" in draft.content and "盒子A5" in draft.content


async def test_distill_failure_returns_none(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LLM 抛错 → 返回 None（调用方兜底存原文），不抛。"""

    class _LLM:
        async def ainvoke(self, *a: Any, **k: Any) -> Any:
            raise RuntimeError("模型不可用")

    assert (
        await organizational_memory.distill_conversation(
            db,
            DistillConversationCommand(transcript="内容"),
            llm_factory=lambda *args, **kwargs: _LLM(),
        )
        is None
    )


# ── archive_old 集成：存提炼版 / 兜底原文 ────────────────
async def _seed_old_messages(db: AsyncSession) -> SysUser:
    user = SysUser(id=uuid.uuid4(), username="u1", password_hash="x", real_name="张三")
    db.add(user)
    await db.commit()
    old_time = datetime.now(UTC) - timedelta(days=40)
    for i in range(3):
        m = DesktopMessage(
            owner_user_id=user.id,
            speaker_type=SPEAKER_USER,
            speaker_name="张三",
            content=f"消息{i}",
        )
        db.add(m)
        await db.flush()
        m.create_time = old_time  # 强制为旧消息
    await db.commit()
    return user


def _principal(user: SysUser) -> Principal:
    return Principal(
        id=user.id,
        display_name=user.real_name or user.username,
        department_id=user.department_id,
    )


async def test_archive_stores_distilled(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """提炼成功 → 归档标题带「记忆」，入库文本为提炼版。"""
    user = await _seed_old_messages(db)
    captured: dict[str, Any] = {}

    async def _fake_distill(_db: Any, command: Any, **kw: Any) -> MemoryDraft:
        return MemoryDraft(
            content="## 摘要\n提炼后的记忆内容",
            source_type=command.source_type,
            source_id=command.source_id,
        )

    async def _fake_ingest(_db: Any, command: Any) -> None:
        captured["title"] = command.title
        captured["text"] = command.text

    monkeypatch.setattr(organizational_memory, "distill_conversation", _fake_distill)
    monkeypatch.setattr(knowledge_indexing, "index_text", _fake_ingest)
    n = await assistant_conversations.archive_old(db, _principal(user), days=10)
    assert n == 3
    assert "记忆" in captured["title"] and "提炼后的记忆" in captured["text"]
    # 旧消息已删
    remaining = (await db.execute(select(DesktopMessage))).scalars().all()
    assert len(remaining) == 0


async def test_archive_falls_back_to_raw(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """提炼失败(None) → 归档标题带「存档」，入库文本为原始 transcript（不丢数据）。"""
    user = await _seed_old_messages(db)
    captured: dict[str, Any] = {}

    async def _fail_distill(_db: Any, command: Any, **kw: Any) -> None:
        return None

    async def _fake_ingest(_db: Any, command: Any) -> None:
        captured["title"] = command.title
        captured["text"] = command.text

    monkeypatch.setattr(organizational_memory, "distill_conversation", _fail_distill)
    monkeypatch.setattr(knowledge_indexing, "index_text", _fake_ingest)
    await assistant_conversations.archive_old(db, _principal(user), days=10)
    assert "存档" in captured["title"] and "消息0" in captured["text"]  # 原文保底
