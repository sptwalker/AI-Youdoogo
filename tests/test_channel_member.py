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


# ── 群主：解散 + 踢人 ───────────────────────────────────
async def test_creator_is_owner(db: AsyncSession) -> None:
    creator, other = uuid.uuid4(), uuid.uuid4()
    c = await discussion_service.create_channel(db, name="g", creator_id=creator)
    assert await discussion_service.is_owner(db, c.id, creator) is True
    assert await discussion_service.is_owner(db, c.id, other) is False


async def test_disband_soft_deletes_channel_and_members(db: AsyncSession) -> None:
    from app.models.discussion import ChannelMember, DiscussionChannel

    creator, h2 = uuid.uuid4(), uuid.uuid4()
    c = await discussion_service.create_channel(
        db, name="g", creator_id=creator,
        members=[{"member_type": "human", "member_id": h2}],
    )
    await discussion_service.disband_channel(db, c.id)
    # 频道软删
    ch = await db.get(DiscussionChannel, c.id)
    assert ch is not None and ch.is_delete is True
    # 成员软删
    from sqlalchemy import func, select
    live = (await db.execute(
        select(func.count()).select_from(ChannelMember).where(
            ChannelMember.channel_id == c.id, ChannelMember.is_delete.is_(False)
        )
    )).scalar_one()
    assert live == 0
    # 不再出现在任何人的"我的群"
    assert str(c.id) not in await discussion_service.my_channel_ids(db, creator)


async def test_channel_dict_has_creator(db: AsyncSession) -> None:
    """频道字典含 creator_id（前端据此判群主）。"""
    creator = uuid.uuid4()
    await discussion_service.create_channel(db, name="g", creator_id=creator)
    chans = await discussion_service.my_channels_with_unread(db, creator)
    assert chans and chans[0]["creator_id"] == str(creator)


# ── I5 未读计数 ─────────────────────────────────────────
async def test_unread_count(db: AsyncSession) -> None:
    """群内他人发言 → 未读+；mark_read 清零。"""
    from app.models.discussion import DiscussionMessage

    me, other = uuid.uuid4(), uuid.uuid4()
    c = await discussion_service.create_channel(db, name="g", creator_id=me)
    # 他人发 2 条
    for i in range(2):
        db.add(DiscussionMessage(
            channel_id=c.id, speaker_type="human", speaker_id=other,
            speaker_name="他", content=f"msg{i}",
        ))
    await db.commit()
    chans = await discussion_service.my_channels_with_unread(db, me)
    mine = next(x for x in chans if x["id"] == str(c.id))
    assert mine["unread"] == 2
    # 读后清零
    await discussion_service.mark_read(db, c.id, me)
    chans2 = await discussion_service.my_channels_with_unread(db, me)
    assert next(x for x in chans2 if x["id"] == str(c.id))["unread"] == 0


async def test_unread_excludes_own_messages(db: AsyncSession) -> None:
    """自己发的消息不计入未读。"""
    from app.models.discussion import DiscussionMessage

    me = uuid.uuid4()
    c = await discussion_service.create_channel(db, name="g", creator_id=me)
    db.add(DiscussionMessage(
        channel_id=c.id, speaker_type="human", speaker_id=me,
        speaker_name="我", content="自己发的",
    ))
    await db.commit()
    chans = await discussion_service.my_channels_with_unread(db, me)
    assert next(x for x in chans if x["id"] == str(c.id))["unread"] == 0


# ── I7 群聊归档入库 ─────────────────────────────────────
async def test_archive_ingests_to_kb(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """归档群 → 聊天记录提炼入 KB（复用 H3.2）。"""
    from app.models.discussion import DiscussionMessage

    creator = uuid.uuid4()
    c = await discussion_service.create_channel(db, name="项目群", creator_id=creator)
    db.add(DiscussionMessage(
        channel_id=c.id, speaker_type="human", speaker_id=creator,
        speaker_name="张三", content="讨论了运营方案",
    ))
    await db.commit()

    captured: dict[str, object] = {}

    async def _fake_distill(_db: object, transcript: str, **kw: object) -> str:
        return "## 摘要\n讨论运营方案"

    async def _fake_ingest(_db: object, *, title: str, text: str, **kw: object) -> None:
        captured["title"] = title
        captured["text"] = text

    class _KB:
        id = uuid.uuid4()

    async def _fake_kb(_db: object) -> object:
        return _KB()

    from app.knowledge import ingest as ingest_mod
    from app.services import knowledge_base_service, memory_service

    monkeypatch.setattr(memory_service, "distill_conversation", _fake_distill)
    monkeypatch.setattr(ingest_mod, "ingest_text", _fake_ingest)
    monkeypatch.setattr(knowledge_base_service, "get_default_kb", _fake_kb)

    await discussion_service.archive_channel(db, c.id)
    assert "群聊存档" in str(captured.get("title")) and "运营方案" in str(captured.get("text"))
