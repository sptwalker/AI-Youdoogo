"""实时广播内核（I3，docs/18）：Redis 异步发布订阅做多 worker 广播背板。

核心硬缺口:原 SSE 只在"我 POST"时把回复推给我自己，A 发言 B/C 收不到。本模块补
"服务端主动推送"——用 Redis pub/sub 作跨 worker 广播背板:
- publish(channel, event)：把消息发到 Redis 频道，所有订阅者（含别的 worker）都收到。
- subscribe(channels)：异步生成器，长连订阅若干频道，有消息即 yield。
每在线用户开一条 SSE 长连（subscribe 其所在群频道），实现真即时群聊。

用 redis.asyncio（非 shared_state 的同步客户端）——订阅是长生命周期异步流。
降级:Redis 不可用 → subscribe 立即结束（前端可回退轮询），publish 吞异常（不阻断发消息落库）。
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from app.core.config import get_settings
from app.core.sse import Event

logger = logging.getLogger(__name__)

_CHANNEL_PREFIX = "rt:chan:"  # Redis 频道前缀（群聊按 channel_id 分频道）


def channel_key(channel_id: str) -> str:
    """群 → Redis 频道名。"""
    return f"{_CHANNEL_PREFIX}{channel_id}"


async def publish(channel_id: str, event_name: str, data: dict[str, Any]) -> None:
    """把一条事件发布到群频道（所有订阅者含跨 worker 收到）。永不 raise。

    发消息主流程 = 落库(权威) + publish(广播);publish 失败不影响落库，只是实时推送缺失
    （订阅者仍可靠轮询/重连补齐）。
    """
    import redis.asyncio as aioredis

    try:
        client = aioredis.from_url(get_settings().redis_url)
        payload = json.dumps({"event": event_name, "data": data}, ensure_ascii=False)
        await client.publish(channel_key(channel_id), payload)
        await client.aclose()
    except Exception:  # noqa: BLE001 - 广播失败不阻断发消息落库
        logger.warning("实时广播 publish 失败 channel=%s", channel_id, exc_info=True)


async def subscribe(
    channel_ids: list[str],
    *,
    authorize: Callable[[str], Awaitable[bool]] | None = None,
) -> AsyncIterator[Event]:
    """订阅若干群频道，长连生成器:有消息即 yield (event_name, data)。

    含心跳（无消息时定期 yield ping 保活，防中间层断连）。Redis 不可用 → 立即结束
    （调用方 SSE 流随之结束，前端可回退轮询/重连）。
    """
    import redis.asyncio as aioredis

    if not channel_ids:
        return
    client: Any = None
    pubsub: Any = None
    try:
        client = aioredis.from_url(get_settings().redis_url)
        pubsub = client.pubsub()
        await pubsub.subscribe(*[channel_key(c) for c in channel_ids])
        yield ("ready", {"channels": len(channel_ids)})
        while True:
            # 带超时 get_message：有消息即推，无消息超时则发心跳保活
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=25.0)
            if msg is None:
                yield ("ping", {})
                continue
            raw = msg.get("data")
            if raw is None:
                continue
            raw_channel = msg.get("channel")
            channel_key_value = (
                raw_channel
                if isinstance(raw_channel, str)
                else raw_channel.decode("utf-8")
                if isinstance(raw_channel, bytes)
                else ""
            )
            channel_id = (
                channel_key_value.removeprefix(_CHANNEL_PREFIX)
                if channel_key_value.startswith(_CHANNEL_PREFIX)
                else ""
            )
            if authorize is not None and (
                not channel_id or not await authorize(channel_id)
            ):
                logger.info("实时消息因成员权限已撤销而丢弃 channel=%s", channel_id)
                continue
            try:
                parsed = json.loads(raw if isinstance(raw, str) else raw.decode("utf-8"))
                yield (str(parsed.get("event") or "message"), parsed.get("data") or {})
            except (json.JSONDecodeError, AttributeError, UnicodeDecodeError):
                logger.warning("实时订阅收到无法解析的消息，已跳过")
    except Exception:  # noqa: BLE001 - Redis 不可用/订阅故障：结束流，前端回退轮询
        logger.warning("实时订阅中断 channels=%s", channel_ids, exc_info=True)
    finally:
        if pubsub is not None:
            try:
                await pubsub.aclose()
            except Exception:  # noqa: BLE001
                pass
        if client is not None:
            try:
                await client.aclose()
            except Exception:  # noqa: BLE001
                pass
