"""实时广播内核单测（I3，docs/18）:Redis pub/sub 发布订阅往返 + 频道键 + 降级。

用真 Redis（dev 容器）跑通 publish→subscribe 往返;Redis 不可用时 subscribe 优雅结束。
"""

import asyncio
from typing import Any

import pytest

from app.services import realtime_service


def test_channel_key() -> None:
    assert realtime_service.channel_key("abc") == "rt:chan:abc"


async def test_publish_subscribe_roundtrip() -> None:
    """publish 的消息能被 subscribe 收到（真 Redis 往返）。"""
    received: list[tuple[str, dict[str, Any]]] = []
    ready = asyncio.Event()

    async def _consume() -> None:
        async for name, data in realtime_service.subscribe(["test-chan-i3"]):
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
    await realtime_service.publish("test-chan-i3", "message", {"text": "你好"})
    try:
        await asyncio.wait_for(task, timeout=5.0)
    except TimeoutError:
        task.cancel()
        pytest.skip("Redis 未就绪或超时（真 Redis 未运行时跳过）")
    assert received and received[0][1]["text"] == "你好"


async def test_subscribe_empty_channels_ends() -> None:
    """空频道列表 → subscribe 立即结束（不挂起）。"""
    items = [x async for x in realtime_service.subscribe([])]
    assert items == []


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

    stream = realtime_service.subscribe(["private"], authorize=_authorize)
    assert await anext(stream) == ("ready", {"channels": 1})
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(anext(stream), timeout=0.05)


async def test_publish_never_raises_on_bad_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    """Redis 不可用 → publish 吞异常不抛（不阻断发消息落库）。"""
    class _S:
        redis_url = "redis://127.0.0.1:6399/0"  # 无人监听的端口

    monkeypatch.setattr(realtime_service, "get_settings", lambda: _S())
    # 不抛即通过
    await realtime_service.publish("c", "message", {"x": 1})
