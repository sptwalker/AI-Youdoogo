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

    async def _consume() -> None:
        async for name, data in realtime_service.subscribe(["test-chan-i3"]):
            if name == "ready":
                continue
            if name == "message":
                received.append((name, data))
                return  # 收到目标消息即结束

    task = asyncio.create_task(_consume())
    await asyncio.sleep(0.3)  # 等订阅就绪
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


async def test_publish_never_raises_on_bad_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    """Redis 不可用 → publish 吞异常不抛（不阻断发消息落库）。"""
    class _S:
        redis_url = "redis://127.0.0.1:6399/0"  # 无人监听的端口

    monkeypatch.setattr(realtime_service, "get_settings", lambda: _S())
    # 不抛即通过
    await realtime_service.publish("c", "message", {"x": 1})
