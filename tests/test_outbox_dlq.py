"""Outbox DLQ 仓储操作 + Admin 死信端点（查看/重放）测试。

仓储级用 in-memory sqlite 走真实 enqueue→claim→fail 到 FAILED 终态；HTTP 级复用
admin_client fixture（dependency_overrides[get_db] + 真实 create_access_token + Bearer）。
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.models import Base
from app.models.system import SysUser
from app.platform import outbox

_SessionMaker = async_sessionmaker[AsyncSession]
_AdminClient = tuple[AsyncClient, str, _SessionMaker]


async def _fail_one(db: AsyncSession, *, dedupe: str) -> uuid.UUID:
    """enqueue → claim → fail 到 FAILED 终态（max_attempts=1，一次失败即终态），返回 event_id。"""
    event = await outbox.enqueue(
        db,
        aggregate_type="test",
        aggregate_id=uuid.uuid4(),
        event_type="test.event",
        dedupe_key=dedupe,
        max_attempts=1,
    )
    event_id = event.id
    await db.commit()
    claimed = await outbox.claim_next(db, worker_id="w", lease_seconds=60)
    assert claimed is not None and claimed.attempts == 1
    assert await outbox.fail(db, claimed, worker_id="w", error="boom", retry_delay_seconds=0)
    await db.commit()
    await db.refresh(claimed)
    assert claimed.status == outbox.OUTBOX_FAILED
    return event_id


@pytest.fixture
async def maker() -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def test_list_failed_returns_dead_letters(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    async with maker() as db:
        await _fail_one(db, dedupe=f"a:{uuid.uuid4()}")
        rows, total = await outbox.list_failed(db, limit=10)
        assert total == 1
        assert len(rows) == 1
        assert rows[0].status == outbox.OUTBOX_FAILED
        assert rows[0].last_error == "boom"


async def test_replay_moves_failed_back_to_pending(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    async with maker() as db:
        event_id = await _fail_one(db, dedupe=f"b:{uuid.uuid4()}")
        assert await outbox.replay(db, event_id)
        await db.commit()
        event = await db.get(outbox.OutboxEvent, event_id)
        assert event is not None
        assert event.status == outbox.OUTBOX_PENDING
        assert event.attempts == 0
        assert event.last_error is None
        # 重放后 worker 能再领
        claimed = await outbox.claim_next(db, worker_id="w2", lease_seconds=60)
        assert claimed is not None and claimed.id == event_id


async def test_replay_rejects_non_failed_and_missing(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    # 信任边界：只从 FAILED 迁出，不重放活跃/不存在事件（否则重复投递在途事件）。
    async with maker() as db:
        assert await outbox.replay(db, uuid.uuid4()) is False  # 不存在
        pending = await outbox.enqueue(
            db,
            aggregate_type="test",
            aggregate_id=uuid.uuid4(),
            event_type="test.event",
            dedupe_key=f"c:{uuid.uuid4()}",
        )
        await db.commit()
        assert await outbox.replay(db, pending.id) is False  # PENDING 非 failed


async def test_backlog_counts_by_status(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    async with maker() as db:
        await _fail_one(db, dedupe=f"d:{uuid.uuid4()}")
        await outbox.enqueue(
            db,
            aggregate_type="test",
            aggregate_id=uuid.uuid4(),
            event_type="test.event",
            dedupe_key=f"e:{uuid.uuid4()}",
        )
        await db.commit()
        counts = await outbox.backlog_counts(db)
        assert counts.get(outbox.OUTBOX_FAILED) == 1
        assert counts.get(outbox.OUTBOX_PENDING) == 1


@pytest.fixture
async def admin_client() -> AsyncGenerator[_AdminClient, None]:
    """Admin 客户端 + member token（权限门测试）+ session factory（造死信）。"""
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    admin_id = uuid.uuid4()
    member_id = uuid.uuid4()
    async with sessions() as session:
        session.add(
            SysUser(id=admin_id, username="dlq-admin", password_hash="x", role_code="admin")
        )
        session.add(
            SysUser(id=member_id, username="dlq-member", password_hash="x", role_code="member")
        )
        await session.commit()

    async def override_db() -> AsyncGenerator[AsyncSession, None]:
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    token = create_access_token(admin_id, "admin")
    member_token = create_access_token(member_id, "member")
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        yield client, member_token, sessions
    app.dependency_overrides.clear()
    await engine.dispose()


async def test_dead_letters_endpoint_lists_and_gates(
    admin_client: _AdminClient,
) -> None:
    client, member_token, sessions = admin_client
    async with sessions() as db:
        await _fail_one(db, dedupe=f"http:{uuid.uuid4()}")

    resp = await client.get("/api/v1/outbox/dead-letters")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total"] == 1
    assert data["items"][0]["last_error"] == "boom"

    # member 被 require_roles("admin") 拒
    denied = await client.get(
        "/api/v1/outbox/dead-letters",
        headers={"Authorization": f"Bearer {member_token}"},
    )
    assert denied.status_code == 403


async def test_replay_endpoint_audits_and_rejects_missing(
    admin_client: _AdminClient,
) -> None:
    client, _, sessions = admin_client
    async with sessions() as db:
        event_id = await _fail_one(db, dedupe=f"replay:{uuid.uuid4()}")

    resp = await client.post(f"/api/v1/outbox/dead-letters/{event_id}/replay")
    assert resp.status_code == 200
    async with sessions() as db:
        event = await db.get(outbox.OutboxEvent, event_id)
        assert event is not None and event.status == outbox.OUTBOX_PENDING

    # 重放不存在事件 → RuleViolation（非 2xx）
    missing = await client.post(f"/api/v1/outbox/dead-letters/{uuid.uuid4()}/replay")
    assert missing.status_code >= 400
