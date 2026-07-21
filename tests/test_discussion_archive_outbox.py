"""解散群归档的事务性 Outbox、重试、恢复与幂等回归测试。"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import Base
from app.models.discussion import ChannelMember, DiscussionChannel, DiscussionMessage
from app.models.knowledge import KnowledgeBase, KnowledgeFile, KnowledgeVector
from app.models.system import SysUser
from app.models.workflow import OUTBOX_DONE, OUTBOX_FAILED, OUTBOX_PENDING, OutboxEvent
from app.services import discussion_service, outbox_service, workflow_worker


@pytest.fixture
async def maker(
    tmp_path: Path,
) -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'discussion-outbox.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def _create_channel(db: AsyncSession) -> DiscussionChannel:
    creator = uuid.uuid4()
    channel = await discussion_service.create_channel(
        db,
        name="项目归档群",
        creator_id=creator,
        members=[{"member_type": "human", "member_id": uuid.uuid4()}],
    )
    db.add(
        DiscussionMessage(
            channel_id=channel.id,
            speaker_type="human",
            speaker_id=creator,
            speaker_name="张三",
            content="确认按新方案推进",
        )
    )
    await db.commit()
    return channel


async def test_disband_and_archive_event_commit_atomically(
    maker: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    async with maker() as db:
        channel = await _create_channel(db)
        channel_id = channel.id

        async def _fail_enqueue(*args: object, **kwargs: object) -> OutboxEvent:
            raise RuntimeError("outbox unavailable")

        monkeypatch.setattr(outbox_service, "enqueue", _fail_enqueue)
        with pytest.raises(RuntimeError, match="outbox unavailable"):
            await discussion_service.disband_channel(db, channel_id)

        current = await db.get(DiscussionChannel, channel_id)
        assert current is not None and current.is_delete is False
        live_members = (
            await db.execute(
                select(func.count())
                .select_from(ChannelMember)
                .where(
                    ChannelMember.channel_id == channel_id,
                    ChannelMember.is_delete.is_(False),
                )
            )
        ).scalar_one()
        assert live_members == 2


async def test_worker_processes_persisted_archive_after_new_session(
    maker: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    async with maker() as setup:
        channel = await _create_channel(setup)
        await discussion_service.disband_channel(setup, channel.id)
        event = (
            await setup.execute(
                select(OutboxEvent).where(
                    OutboxEvent.event_type == discussion_service.DISBAND_ARCHIVE_EVENT
                )
            )
        ).scalar_one()
        event_id = event.id

    archived: list[uuid.UUID] = []

    async def _fake_archive(_db: AsyncSession, channel_id: uuid.UUID) -> None:
        archived.append(channel_id)

    monkeypatch.setattr(discussion_service, "archive_disbanded_channel", _fake_archive)
    async with maker() as restarted_worker:
        assert await workflow_worker.process_one(restarted_worker, worker_id="restarted")
        current = await restarted_worker.get(OutboxEvent, event_id)
        assert current is not None and current.status == OUTBOX_DONE
    assert archived == [channel.id]


async def test_outbox_lease_renewal_requires_current_owner(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    async with maker() as db:
        channel = await _create_channel(db)
        await discussion_service.disband_channel(db, channel.id)
        event = await outbox_service.claim_next(db, worker_id="lease-owner", lease_seconds=10)
        assert event is not None
        await db.commit()
        previous_lease = event.lease_until

        assert not await outbox_service.renew_lease(
            db, event.id, worker_id="other-worker", lease_seconds=60
        )
        assert await outbox_service.renew_lease(
            db, event.id, worker_id="lease-owner", lease_seconds=60
        )
        await db.commit()
        await db.refresh(event)
        assert event.lease_until is not None and previous_lease is not None
        assert event.lease_until > previous_lease


async def test_archive_failure_retries_without_reverting_disband(
    maker: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    async with maker() as db:
        channel = await _create_channel(db)
        await discussion_service.disband_channel(db, channel.id)
        calls = 0

        async def _flaky_archive(_db: AsyncSession, _channel_id: uuid.UUID) -> None:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("temporary archive failure")

        monkeypatch.setattr(discussion_service, "archive_disbanded_channel", _flaky_archive)
        with pytest.raises(RuntimeError, match="temporary archive failure"):
            await workflow_worker.process_one(db, worker_id="retry-worker")

        event = (
            await db.execute(
                select(OutboxEvent).where(
                    OutboxEvent.event_type == discussion_service.DISBAND_ARCHIVE_EVENT
                )
            )
        ).scalar_one()
        assert event.status == OUTBOX_PENDING
        assert event.attempts == 1
        assert event.last_error == "temporary archive failure"
        channel_row = await db.get(DiscussionChannel, channel.id)
        assert channel_row is not None and channel_row.is_delete is True

        event.available_at = outbox_service.utcnow() - timedelta(seconds=1)
        await db.commit()
        assert await workflow_worker.process_one(db, worker_id="retry-worker")
        await db.refresh(event)
        assert calls == 2 and event.status == OUTBOX_DONE


async def test_terminal_archive_failure_is_observable_in_outbox(
    maker: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    async with maker() as db:
        channel = await _create_channel(db)
        await discussion_service.disband_channel(db, channel.id)
        event = (
            await db.execute(
                select(OutboxEvent).where(
                    OutboxEvent.event_type == discussion_service.DISBAND_ARCHIVE_EVENT
                )
            )
        ).scalar_one()
        event.max_attempts = 1
        await db.commit()

        async def _fail_archive(_db: AsyncSession, _channel_id: uuid.UUID) -> None:
            raise RuntimeError("permanent archive failure")

        monkeypatch.setattr(discussion_service, "archive_disbanded_channel", _fail_archive)
        with pytest.raises(RuntimeError, match="permanent archive failure"):
            await workflow_worker.process_one(db, worker_id="terminal-worker")

        await db.refresh(event)
        assert event.status == OUTBOX_FAILED
        assert event.last_error == "permanent archive failure"
        channel_row = await db.get(DiscussionChannel, channel.id)
        assert channel_row is not None and channel_row.is_delete is True


async def test_archive_replay_reuses_deterministic_knowledge_file(
    maker: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.knowledge import ingest as ingest_module
    from app.services import memory_service

    async with maker() as db:
        user = SysUser(username="archive-owner", password_hash="x", role_code="admin")
        kb = KnowledgeBase(
            name="公司公共库",
            code="default",
            scope="company",
            is_default=True,
        )
        db.add_all([user, kb])
        await db.commit()
        channel = await discussion_service.create_channel(
            db, name="幂等群", creator_id=user.id
        )
        db.add(
            DiscussionMessage(
                channel_id=channel.id,
                speaker_type="human",
                speaker_id=user.id,
                speaker_name="归档人",
                content="形成唯一归档",
            )
        )
        await db.commit()

        async def _distill(_db: AsyncSession, _transcript: str, **kwargs: object) -> str:
            return "## 摘要\n形成唯一归档"

        async def _embed(texts: list[str]) -> list[list[float]]:
            return [[0.0] * 1024 for _ in texts]

        monkeypatch.setattr(memory_service, "distill_conversation", _distill)
        monkeypatch.setattr(ingest_module, "embed_texts", _embed)

        await discussion_service.archive_disbanded_channel(db, channel.id)
        await discussion_service.archive_disbanded_channel(db, channel.id)

        files = (
            await db.execute(
                select(KnowledgeFile).where(KnowledgeFile.category == "discussion")
            )
        ).scalars().all()
        vector_count = (
            await db.execute(select(func.count()).select_from(KnowledgeVector))
        ).scalar_one()
        assert len(files) == 1
        assert files[0].id == discussion_service._archive_file_id(channel.id)
        assert files[0].status == "indexed"
        assert vector_count == 1
