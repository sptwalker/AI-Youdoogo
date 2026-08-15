"""B1.1 个人知识库归真人 ensure_personal_kb 单测（docs/27 阶段 B）。

owner 落值 + get-or-create 幂等：验证个人库 scope=personal、owner_user_id=本人、
code 唯一，且重复调不建第二个。离线 sqlite。
"""

import uuid
from collections.abc import AsyncGenerator

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.contexts.foundations.knowledge.wiki_management.public import ensure_personal_kb
from app.models import Base
from app.models.knowledge import KnowledgeBase


@pytest.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


async def test_creates_personal_kb_owned_by_user(db: AsyncSession) -> None:
    user_id = uuid.uuid4()
    kb_id = await ensure_personal_kb(db, user_id)
    row = await db.get(KnowledgeBase, kb_id)
    assert row is not None
    assert row.owner_user_id == user_id
    assert row.scope == "personal"
    assert row.code == f"personal:{user_id}"


async def test_get_or_create_is_idempotent(db: AsyncSession) -> None:
    user_id = uuid.uuid4()
    first = await ensure_personal_kb(db, user_id)
    second = await ensure_personal_kb(db, user_id)
    assert first == second
    total = (
        await db.execute(
            select(func.count())
            .select_from(KnowledgeBase)
            .where(KnowledgeBase.owner_user_id == user_id)
        )
    ).scalar_one()
    assert total == 1  # 重复调只保留一个个人库


async def test_personal_kbs_are_per_user(db: AsyncSession) -> None:
    a, b = await ensure_personal_kb(db, uuid.uuid4()), await ensure_personal_kb(db, uuid.uuid4())
    assert a != b  # 不同真人各有独立个人库
