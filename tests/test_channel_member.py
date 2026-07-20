"""群成员单测（I4，docs/18）:加/退成员、我的群、成员守卫、创建者自动入群。"""

import uuid
from collections.abc import AsyncGenerator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import Base
from app.services import discussion_service


@pytest.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


async def test_creator_auto_joins(db: AsyncSession) -> None:
    """建群 → 创建者自动成为成员。"""
    creator = uuid.uuid4()
    c = await discussion_service.create_channel(db, name="项目群", creator_id=creator)
    assert await discussion_service.is_member(db, c.id, creator) is True
    ids = await discussion_service.my_channel_ids(db, creator)
    assert str(c.id) in ids


async def test_create_with_mixed_members(db: AsyncSession) -> None:
    """建群带真人+AI 混合初始成员。"""
    creator, human2, ai1 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    c = await discussion_service.create_channel(
        db, name="混合群", creator_id=creator,
        members=[
            {"member_type": "human", "member_id": human2, "member_name": "李四"},
            {"member_type": "ai", "member_id": ai1, "member_name": "顾问A"},
        ],
    )
    members = await discussion_service.list_members(db, c.id)
    types = {m["member_type"] for m in members}
    assert types == {"human", "ai"} and len(members) == 3  # 创建者+2


async def test_add_members_idempotent(db: AsyncSession) -> None:
    creator, h2 = uuid.uuid4(), uuid.uuid4()
    c = await discussion_service.create_channel(db, name="g", creator_id=creator)
    n1 = await discussion_service.add_members(
        db, c.id, [{"member_type": "human", "member_id": h2}]
    )
    n2 = await discussion_service.add_members(
        db, c.id, [{"member_type": "human", "member_id": h2}]
    )
    assert n1 == 1 and n2 == 0  # 重复不加


async def test_remove_member(db: AsyncSession) -> None:
    creator, h2 = uuid.uuid4(), uuid.uuid4()
    c = await discussion_service.create_channel(
        db, name="g", creator_id=creator,
        members=[{"member_type": "human", "member_id": h2}],
    )
    assert await discussion_service.is_member(db, c.id, h2) is True
    await discussion_service.remove_member(db, c.id, "human", h2)
    assert await discussion_service.is_member(db, c.id, h2) is False


async def test_non_member_not_in_my_channels(db: AsyncSession) -> None:
    """非成员的群不出现在其"我的群"。"""
    creator, outsider = uuid.uuid4(), uuid.uuid4()
    c = await discussion_service.create_channel(db, name="私群", creator_id=creator)
    assert str(c.id) not in await discussion_service.my_channel_ids(db, outsider)
    assert await discussion_service.is_member(db, c.id, outsider) is False
