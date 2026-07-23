"""SSE 端点测试：/desktop/chat 逐字流式（假模型 + 内存 SQLite + ASGI 直连）。

同时证实：yield 依赖注入的 DB session 在 StreamingResponse 流完前保持可用
（流完后 AI 消息已落库）。
"""

import json
from collections.abc import AsyncGenerator, AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from langchain_core.messages import AIMessageChunk
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.agents import base
from app.core.database import get_db
from app.core.security import hash_password
from app.main import app
from app.models import Base
from app.models.desktop import DesktopMessage
from app.models.system import SysUser


class _FakeLLM:
    async def astream(self, messages: list, **kwargs: object) -> AsyncIterator[AIMessageChunk]:
        yield AIMessageChunk(content="你好")
        yield AIMessageChunk(content="，我是助理。")


@pytest.fixture
async def ctx(monkeypatch: pytest.MonkeyPatch) -> AsyncGenerator[tuple[AsyncClient, object], None]:
    monkeypatch.setattr(base, "get_llm_for_role", lambda *a, **k: _FakeLLM())
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        s.add(
            SysUser(
                username="alice",
                password_hash=hash_password("pass-word-8"),
                real_name="爱丽丝",
                role_code="member",
            )
        )
        await s.commit()

    async def _override_db() -> AsyncGenerator:
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c, factory
    app.dependency_overrides.clear()
    await engine.dispose()


def _parse(body: str) -> list[tuple[str, dict]]:
    events = []
    for frame in body.split("\n\n"):
        if not frame.strip():
            continue
        lines = dict(line.split(": ", 1) for line in frame.splitlines())
        events.append((lines["event"], json.loads(lines["data"])))
    return events


async def test_desktop_chat_sse(ctx: tuple[AsyncClient, object]) -> None:
    client, factory = ctx
    resp = await client.post(
        "/api/v1/auth/login", json={"username": "alice", "password": "pass-word-8"}
    )
    token = resp.json()["data"]["access_token"]

    async with client.stream(
        "POST",
        "/api/v1/desktop/chat",
        json={"message": "在吗", "add_agent_ids": []},
        headers={"Authorization": f"Bearer {token}"},
    ) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        body = "".join([chunk async for chunk in r.aiter_text()])

    events = _parse(body)
    names = [n for n, _ in events]
    # 用户回显 → 助理 message_start → delta+ → message_end → done
    assert names[0] == "message_end" and events[0][1]["speaker_type"] == "user"
    assert "message_start" in names and names.count("delta") >= 2
    assert names[-1] == "done"
    ai_end = [d for n, d in events if n == "message_end" and d["speaker_type"] == "ai"]
    assert ai_end and ai_end[0]["content"] == "你好，我是助理。"
    # 流完后 AI 消息已落库（session 生命周期覆盖整个流）
    async with factory() as s:  # type: ignore[operator]
        n = (
            await s.execute(
                select(func.count())
                .select_from(DesktopMessage)
                .where(DesktopMessage.speaker_type == "ai")
            )
        ).scalar_one()
    assert n == 1


async def test_desktop_chat_get_preserves_envelope_and_owner_history(
    ctx: tuple[AsyncClient, object],
) -> None:
    client, factory = ctx
    async with factory() as session:  # type: ignore[operator]
        alice = (
            await session.execute(select(SysUser).where(SysUser.username == "alice"))
        ).scalar_one()
        other = SysUser(username="bob", password_hash="x", real_name="鲍勃")
        session.add(other)
        await session.commit()
        session.add_all(
            [
                DesktopMessage(
                    owner_user_id=alice.id,
                    speaker_type="user",
                    speaker_name="爱丽丝",
                    content="我的消息",
                ),
                DesktopMessage(
                    owner_user_id=other.id,
                    speaker_type="user",
                    speaker_name="鲍勃",
                    content="别人的消息",
                ),
            ]
        )
        await session.commit()

    login = await client.post(
        "/api/v1/auth/login",
        json={"username": "alice", "password": "pass-word-8"},
    )
    token = login.json()["data"]["access_token"]
    response = await client.get(
        "/api/v1/desktop/chat",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] == 0
    assert payload["data"]["assistant"]["name"] == "爱丽丝的助理"
    assert [message["content"] for message in payload["data"]["messages"]] == ["我的消息"]
    assert payload["data"]["addable_agents"] == []


async def test_desktop_chat_sse_unauthorized(ctx: tuple[AsyncClient, object]) -> None:
    client, _ = ctx
    resp = await client.post("/api/v1/desktop/chat", json={"message": "在吗"})
    assert resp.status_code == 401
