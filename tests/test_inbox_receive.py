"""receive_event 幂等落库（docs/23 §3.2）：首收 True 落一行，同 event_id 重投 False 不重复。

离线 sqlite StaticPool，直测 inbox.receive_event 的 existing 去重 + INSERT 分支（此前仅在 live 门禁
跑过，离线套件未覆盖 63-79）。并发 IntegrityError 竞态分支单线程无法确定性触发，留 live 门禁证。
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.models import Base
from app.platform.eventing.inbox import EventEnvelope, receive_event
from app.platform.eventing.inbox_model import InboxEvent


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        yield s
    await engine.dispose()


def _envelope(event_id: uuid.UUID) -> EventEnvelope:
    return EventEnvelope(
        event_id=event_id,
        event_type="step.ready",
        aggregate_type="workflow_step",
        aggregate_id=uuid.uuid4(),
        payload={"k": "v"},
        dedupe_key="d1",
    )


async def _count(session: AsyncSession) -> int:
    return (await session.execute(select(func.count()).select_from(InboxEvent))).scalar_one()


async def test_first_receive_persists_once(session: AsyncSession) -> None:
    assert await receive_event(session, _envelope(uuid.uuid4()), source="peer") is True
    await session.flush()
    assert await _count(session) == 1


async def test_duplicate_event_id_deduped(session: AsyncSession) -> None:
    eid = uuid.uuid4()
    assert await receive_event(session, _envelope(eid), source="peer") is True
    await session.flush()
    # 同 event_id 重投 → False（existing 去重），仍恰一行（逻辑上只处理一次）。
    assert await receive_event(session, _envelope(eid), source="peer") is False
    assert await _count(session) == 1
