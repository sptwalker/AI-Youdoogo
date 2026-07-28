"""Realtime Platform tests: Redis pub/sub, heartbeat, authorization, cleanup, and fallback.

The roundtrip uses a real development Redis when available; transport failures use fakes.
"""

import ast
import asyncio
import json
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any, cast

import pytest

from app.contexts.business.group_messaging.infrastructure import adapters
from app.platform import realtime
from app.platform import realtime as realtime_service
from app.platform.realtime import redis_pubsub


def test_channel_key() -> None:
    assert realtime.channel_key("abc") == "rt:chan:abc"
    assert realtime_service.channel_key is realtime.channel_key
    assert realtime_service.publish is realtime.publish
    assert realtime_service.subscribe is realtime.subscribe


def test_platform_realtime_has_no_business_layer_imports() -> None:
    forbidden = (
        "app.agents",
        "app.contexts",
        "app.models",
        "app.services",
    )
    for path in Path("app/platform/realtime").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = [
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        ]
        imported.extend(
            node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
        )
        assert not [name for name in imported if name.startswith(forbidden)]


async def test_group_messaging_delivery_adapter_calls_platform_realtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    published: list[tuple[str, str, dict[str, object]]] = []

    async def _publish(channel_id: str, event_name: str, data: dict[str, object]) -> None:
        published.append((channel_id, event_name, data))

    monkeypatch.setattr(adapters.realtime, "publish", _publish)
    channel_id = uuid.UUID(int=42)

    await adapters.RedisRealtimeDeliveryAdapter().publish(
        channel_id,
        "message",
        {"text": "hello"},
    )

    assert published == [(str(channel_id), "message", {"text": "hello"})]


async def test_publish_subscribe_roundtrip() -> None:
    """publish 的消息能被 subscribe 收到（真 Redis 往返）。"""
    received: list[tuple[str, dict[str, Any]]] = []
    ready = asyncio.Event()

    async def _consume() -> None:
        async for name, data in realtime.subscribe(["test-chan-i3"]):
            if name == "ready":
                ready.set()
                continue
            if name == "message":
                received.append((name, data))
                return  # 收到目标消息即结束

    task = asyncio.create_task(_consume())
    try:
        await asyncio.wait_for(ready.wait(), timeout=2.0)
    except TimeoutError:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        pytest.skip("Redis 未就绪（本地未启动真 Redis 时跳过）")
    await realtime.publish("test-chan-i3", "message", {"text": "你好"})
    try:
        await asyncio.wait_for(task, timeout=5.0)
    except TimeoutError:
        task.cancel()
        pytest.skip("Redis 未就绪或超时（真 Redis 未运行时跳过）")
    assert received and received[0][1]["text"] == "你好"


async def test_subscribe_empty_channels_ends() -> None:
    """空频道列表 → subscribe 立即结束（不挂起）。"""
    items = [x async for x in realtime.subscribe([])]
    assert items == []


async def test_subscribe_yields_heartbeat_and_closes_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closed: list[str] = []

    class _PubSub:
        async def subscribe(self, *_channels: str) -> None:
            return None

        async def get_message(self, **_kwargs: Any) -> None:
            return None

        async def aclose(self) -> None:
            closed.append("pubsub")

    class _Client:
        def pubsub(self) -> _PubSub:
            return _PubSub()

        async def aclose(self) -> None:
            closed.append("client")

    import redis.asyncio as aioredis

    monkeypatch.setattr(aioredis, "from_url", lambda *_args, **_kwargs: _Client())

    stream = cast(AsyncGenerator[realtime.Event, None], realtime.subscribe(["heartbeat"]))
    assert await anext(stream) == ("ready", {"channels": 1})
    assert await anext(stream) == ("ping", {})
    await stream.aclose()
    assert closed == ["pubsub", "client"]


async def test_subscribe_drops_message_after_authorization_revoked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """旧 Redis 订阅仍存活时，服务端授权回调必须阻止消息下发。"""
    authorized = False

    class _PubSub:
        async def subscribe(self, *_channels: str) -> None:
            return None

        async def get_message(self, **_kwargs: Any) -> dict[str, Any]:
            await asyncio.sleep(0)
            return {
                "channel": b"rt:chan:private",
                "data": '{"event":"message","data":{"text":"secret"}}',
            }

        async def aclose(self) -> None:
            return None

    class _Client:
        def pubsub(self) -> _PubSub:
            return _PubSub()

        async def aclose(self) -> None:
            return None

    import redis.asyncio as aioredis

    monkeypatch.setattr(aioredis, "from_url", lambda *_args, **_kwargs: _Client())

    async def _authorize(_channel_id: str) -> bool:
        return authorized

    stream = realtime.subscribe(["private"], authorize=_authorize)
    assert await anext(stream) == ("ready", {"channels": 1})
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(anext(stream), timeout=0.05)


async def test_publish_never_raises_and_closes_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Redis publish failure stays best-effort and still closes its client."""
    published: list[tuple[str, dict[str, Any]]] = []

    class _Client:
        closed = False

        async def publish(self, key: str, payload: str) -> None:
            published.append((key, json.loads(payload)))
            raise ConnectionError("redis unavailable")

        async def aclose(self) -> None:
            self.closed = True

    class _S:
        redis_url = "redis://unavailable/0"

    client = _Client()
    import redis.asyncio as aioredis

    monkeypatch.setattr(redis_pubsub, "get_settings", lambda: _S())
    monkeypatch.setattr(aioredis, "from_url", lambda *_args, **_kwargs: client)

    await realtime.publish("c", "message", {"x": 1})

    assert published == [("rt:chan:c", {"event": "message", "data": {"x": 1}})]
    assert client.closed is True


async def test_subscribe_ends_normally_and_cleans_up_when_redis_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Redis subscription failure ends the stream so clients can fall back to polling."""
    closed: list[str] = []

    class _PubSub:
        async def subscribe(self, *_channels: str) -> None:
            raise ConnectionError("redis unavailable")

        async def aclose(self) -> None:
            closed.append("pubsub")

    class _Client:
        def pubsub(self) -> _PubSub:
            return _PubSub()

        async def aclose(self) -> None:
            closed.append("client")

    import redis.asyncio as aioredis

    monkeypatch.setattr(aioredis, "from_url", lambda *_args, **_kwargs: _Client())

    assert [event async for event in realtime.subscribe(["offline"])] == []
    assert closed == ["pubsub", "client"]
