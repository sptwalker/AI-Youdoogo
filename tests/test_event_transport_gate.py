"""事件传输门禁 Go/No-Go 演练（Phase 3 硬前置 / docs/23 §3.4）。

回环（loopback）离线证明「签发→POST→验签→幂等落库→DLQ→重放」这条跨服务传输模板：
Relay 出站 HTTP 经 ASGITransport 打到本服务自己的 /internal/events。sqlite in-memory 单连接
（StaticPool，跨 session 可见），仿 test_outbox_dlq 形态。演练全绿 = 放行 Phase 3 远程事件消费者。
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.core.internal_token import mint_internal_token
from app.main import app
from app.models import Base
from app.platform import eventing, outbox
from app.platform.database import get_db
from app.platform.eventing.relay import EVENTS_SCOPE, HttpInboxRelay

_EVENT_TYPE = "expert.step.ready"
_SessionMaker = async_sessionmaker[AsyncSession]


@pytest.fixture(autouse=True)
def _internal_key() -> None:
    """给进程级 Settings 单例装一把 EC 私钥，令 mint/verify 可用（自签自验）。"""
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    settings = get_settings()
    original = settings.internal_jwt_private_key
    settings.internal_jwt_private_key = pem
    yield
    settings.internal_jwt_private_key = original


@pytest.fixture
async def wired() -> AsyncGenerator[tuple[_SessionMaker, ASGITransport], None]:
    """单连接 in-memory 引擎 + get_db 覆盖 + 指向本 app 的回环 transport。"""
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def override_db() -> AsyncGenerator[AsyncSession, None]:
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    # 入站门默认关 → 显式补挂 /internal/events 一次（app.state 去重）。
    if not getattr(app.state, "_eventing_mounted", False):
        from app.platform.eventing.entrypoints import router as eventing_router

        app.include_router(eventing_router)
        app.state._eventing_mounted = True
    yield sessions, ASGITransport(app=app)
    app.dependency_overrides.clear()
    await engine.dispose()


def _loopback_relay(transport: ASGITransport) -> HttpInboxRelay:
    issuer = get_settings().internal_jwt_issuer
    return HttpInboxRelay(
        peer_url="http://test", audience=issuer, source_service=issuer, transport=transport
    )


async def _enqueue(db: AsyncSession, *, dedupe: str, max_attempts: int = 5) -> uuid.UUID:
    event = await outbox.enqueue(
        db,
        aggregate_type="expert",
        aggregate_id=uuid.uuid4(),
        event_type=_EVENT_TYPE,
        dedupe_key=dedupe,
        payload={"step": "demo"},
        max_attempts=max_attempts,
    )
    await db.commit()
    return event.id


async def _claim_relay_complete(db: AsyncSession, relay: HttpInboxRelay, *, worker: str) -> bool:
    """claim→commit（释放单连接）→relay 投递→成功 complete / 失败 fail。返回是否投递成功。"""
    claimed = await outbox.claim_next(db, worker_id=worker, lease_seconds=60)
    assert claimed is not None
    await db.commit()  # 单连接：投递前先提交 PROCESSING，避免与 inbox 内层 session 事务嵌套
    try:
        await relay(db, claimed)
    except Exception as exc:  # noqa: BLE001 - 门禁要证失败入 DLQ
        assert await outbox.fail(
            db, claimed, worker_id=worker, error=str(exc), retry_delay_seconds=0
        )
        await db.commit()
        return False
    assert await outbox.complete(db, claimed, worker_id=worker)
    await db.commit()
    return True


async def test_relay_delivers_exactly_once(
    wired: tuple[_SessionMaker, ASGITransport],
) -> None:
    sessions, transport = wired
    relay = _loopback_relay(transport)
    async with sessions() as db:
        await _enqueue(db, dedupe=f"one:{uuid.uuid4()}")
        assert await _claim_relay_complete(db, relay, worker="w")
        rows, _ = await _list_inbox(db)
        assert len(rows) == 1 and rows[0].status == eventing.INBOX_RECEIVED
        assert await eventing.process_pending(db) == 1
        await db.commit()


async def test_inbox_idempotent_on_redelivery(
    wired: tuple[_SessionMaker, ASGITransport],
) -> None:
    sessions, transport = wired
    relay = _loopback_relay(transport)
    async with sessions() as db:
        event_id = await _enqueue(db, dedupe=f"dup:{uuid.uuid4()}")
        claimed = await outbox.claim_next(db, worker_id="w", lease_seconds=60)
        assert claimed is not None and claimed.id == event_id
        await db.commit()
        # 同一 event 投两次（模拟网络重试 / 重放）→ inbox 去重，逻辑只处理一次
        await relay(db, claimed)
        await relay(db, claimed)
        rows, _ = await _list_inbox(db)
        assert len(rows) == 1
        assert await eventing.process_pending(db) == 1
        await db.commit()


async def test_inbox_rejects_bad_auth(
    wired: tuple[_SessionMaker, ASGITransport],
) -> None:
    _, transport = wired
    issuer = get_settings().internal_jwt_issuer
    body = {
        "event_id": str(uuid.uuid4()),
        "event_type": _EVENT_TYPE,
        "aggregate_type": "expert",
        "aggregate_id": str(uuid.uuid4()),
        "payload": {},
        "dedupe_key": "x",
    }
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 无令牌 → 拒（401/403，均为未授权）
        assert (await client.post("/internal/events", json=body)).status_code in (401, 403)
        # 无效令牌 → 401（验签失败）
        bad = await client.post(
            "/internal/events", json=body, headers={"Authorization": "Bearer not-a-jwt"}
        )
        assert bad.status_code == 401
        # 有效令牌但缺 events:receive scope → 403
        no_scope = mint_internal_token(service_id="peer", audience=issuer, scope=())
        denied = await client.post(
            "/internal/events", json=body, headers={"Authorization": f"Bearer {no_scope}"}
        )
        assert denied.status_code == 403
        # 有效令牌 + scope → 202
        good = mint_internal_token(service_id="peer", audience=issuer, scope=(EVENTS_SCOPE,))
        ok_resp = await client.post(
            "/internal/events", json=body, headers={"Authorization": f"Bearer {good}"}
        )
        assert ok_resp.status_code == 202
        assert ok_resp.json()["data"]["accepted"] is True


async def test_inbox_5xx_drives_to_dlq_then_replay(
    wired: tuple[_SessionMaker, ASGITransport],
) -> None:
    sessions, good_transport = wired

    fail_app = FastAPI()

    @fail_app.post("/internal/events")
    async def _boom() -> JSONResponse:
        return JSONResponse({"msg": "boom"}, status_code=500)

    issuer = get_settings().internal_jwt_issuer
    fail_relay = HttpInboxRelay(
        peer_url="http://test",
        audience=issuer,
        source_service=issuer,
        transport=ASGITransport(app=fail_app),
    )
    good_relay = _loopback_relay(good_transport)

    async with sessions() as db:
        event_id = await _enqueue(db, dedupe=f"dlq:{uuid.uuid4()}", max_attempts=1)
        # inbox 5xx → relay raise → outbox fail → max_attempts=1 一次即 FAILED（DLQ）
        assert await _claim_relay_complete(db, fail_relay, worker="w") is False
        failed, total = await outbox.list_failed(db, limit=10)
        assert total == 1 and failed[0].id == event_id
        rows, _ = await _list_inbox(db)
        assert len(rows) == 0  # 未落库

        # 重放：FAILED→PENDING → 再驱动至好 inbox → 落一条，逻辑处理一次（跨重放不双写）
        assert await outbox.replay(db, event_id)
        await db.commit()
        assert await _claim_relay_complete(db, good_relay, worker="w2")
        rows, _ = await _list_inbox(db)
        assert len(rows) == 1 and rows[0].event_id == event_id
        assert await eventing.process_pending(db) == 1
        await db.commit()


async def _list_inbox(db: AsyncSession) -> tuple[list[eventing.InboxEvent], int]:
    from sqlalchemy import func, select

    rows = list((await db.execute(select(eventing.InboxEvent))).scalars())
    total = int(
        (await db.execute(select(func.count()).select_from(eventing.InboxEvent))).scalar_one()
    )
    return rows, total


async def test_inbox_mount_gated_by_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """入站门：关 → /internal/events 不存在（404）；开 → 在（鉴权拒 401/403）。"""
    from app.bootstrap.wiring import register_routes

    settings = get_settings()
    body = {
        "event_id": str(uuid.uuid4()),
        "event_type": _EVENT_TYPE,
        "aggregate_type": "expert",
        "aggregate_id": str(uuid.uuid4()),
        "payload": {},
        "dedupe_key": "gate",
    }

    monkeypatch.setattr(settings, "event_inbox_enabled", False)
    off = FastAPI()
    register_routes(off)
    async with AsyncClient(transport=ASGITransport(app=off), base_url="http://test") as c:
        assert (await c.post("/internal/events", json=body)).status_code == 404

    monkeypatch.setattr(settings, "event_inbox_enabled", True)
    on = FastAPI()
    register_routes(on)
    async with AsyncClient(transport=ASGITransport(app=on), base_url="http://test") as c:
        assert (await c.post("/internal/events", json=body)).status_code in (401, 403)
