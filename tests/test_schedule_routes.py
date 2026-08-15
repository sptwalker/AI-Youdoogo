"""B4 个人日程 HTTP 接口：只读拉数（时间线/日历）+ 确认建议，行级隔离 + 红线。"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api import deps
from app.main import app
from app.models import Base
from app.models.system import SysUser
from app.models.time_management import Schedule
from app.platform.database import get_db


@pytest.fixture
async def client(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncGenerator[tuple[AsyncClient, dict[str, Any], dict[str, str]], None]:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    me = SysUser(username="me", password_hash="x", real_name="我", role_code="member")
    other = SysUser(username="other", password_hash="x", role_code="member")
    async with factory() as s:
        s.add_all([me, other])
        await s.commit()
        mine = Schedule(
            owner_id=me.id, title="我的建议日程",
            start_at=datetime(2026, 8, 17, 9, tzinfo=UTC),
            end_at=datetime(2026, 8, 17, 10, tzinfo=UTC),
            source="suggested", status="suggested",
        )
        theirs = Schedule(
            owner_id=other.id, title="他人日程",
            start_at=datetime(2026, 8, 17, 9, tzinfo=UTC),
            end_at=datetime(2026, 8, 17, 10, tzinfo=UTC),
            source="suggested", status="suggested",
        )
        s.add_all([mine, theirs])
        await s.commit()
        ids = {"mine": str(mine.id), "theirs": str(theirs.id)}

    actor: dict[str, Any] = {"user": me}

    async def _override_db() -> AsyncGenerator[AsyncSession, None]:
        async with factory() as s:
            yield s

    async def _current_user() -> SysUser:
        return actor["user"]

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[deps.get_current_user] = _current_user
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c, {"actor": actor}, ids
    app.dependency_overrides.clear()
    await engine.dispose()


async def test_list_only_returns_my_schedules(
    client: tuple[AsyncClient, dict[str, Any], dict[str, str]],
) -> None:
    c, _, _ = client
    resp = await c.get("/api/v1/schedules")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["code"] == 0
    assert [row["title"] for row in payload["data"]] == ["我的建议日程"]  # 行级隔离


async def test_confirm_flips_status_and_isolates_others(
    client: tuple[AsyncClient, dict[str, Any], dict[str, str]],
) -> None:
    c, _, ids = client
    # 确认他人建议 → 命中他人当不存在 404（红线）
    denied = await c.post(f"/api/v1/schedules/{ids['theirs']}/confirm")
    assert denied.status_code == 404

    ok_resp = await c.post(f"/api/v1/schedules/{ids['mine']}/confirm")
    assert ok_resp.status_code == 200
    assert ok_resp.json()["data"]["status"] == "confirmed"  # 真人确认才生效
