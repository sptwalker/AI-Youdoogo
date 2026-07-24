"""Redis pub/sub transport with heartbeat and graceful degradation."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from app.core.config import get_settings

logger = logging.getLogger(__name__)

Event = tuple[str, dict[str, Any]]
ChannelAuthorizer = Callable[[str], Awaitable[bool]]

_CHANNEL_PREFIX = "rt:chan:"
_HEARTBEAT_SECONDS = 25.0


def channel_key(channel_id: str) -> str:
    """Return the Redis pub/sub key for one logical channel."""
    return f"{_CHANNEL_PREFIX}{channel_id}"


async def _close_safely(resource: Any) -> None:
    if resource is None:
        return
    try:
        await resource.aclose()
    except Exception:  # noqa: BLE001 - cleanup must not hide the transport outcome
        pass


async def publish(channel_id: str, event_name: str, data: dict[str, Any]) -> None:
    """Publish an event without letting Redis failure interrupt the caller."""
    import redis.asyncio as aioredis

    client: Any = None
    try:
        client = aioredis.from_url(get_settings().redis_url)
        payload = json.dumps({"event": event_name, "data": data}, ensure_ascii=False)
        await client.publish(channel_key(channel_id), payload)
    except Exception:  # noqa: BLE001 - realtime delivery is an optional best-effort path
        logger.warning("实时广播 publish 失败 channel=%s", channel_id, exc_info=True)
    finally:
        await _close_safely(client)


def _channel_id(raw_channel: object) -> str:
    if isinstance(raw_channel, bytes):
        try:
            value = raw_channel.decode("utf-8")
        except UnicodeDecodeError:
            return ""
    elif isinstance(raw_channel, str):
        value = raw_channel
    else:
        return ""
    return value.removeprefix(_CHANNEL_PREFIX) if value.startswith(_CHANNEL_PREFIX) else ""


def _event(raw: object) -> Event | None:
    if isinstance(raw, str):
        text = raw
    elif isinstance(raw, bytes):
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            logger.warning("实时订阅收到无法解析的消息，已跳过")
            return None
    else:
        logger.warning("实时订阅收到无法解析的消息，已跳过")
        return None
    try:
        payload = json.loads(text)
        return str(payload.get("event") or "message"), payload.get("data") or {}
    except (json.JSONDecodeError, AttributeError):
        logger.warning("实时订阅收到无法解析的消息，已跳过")
        return None


async def subscribe(
    channel_ids: list[str],
    *,
    authorize: ChannelAuthorizer | None = None,
) -> AsyncIterator[Event]:
    """Yield subscribed events and heartbeats, ending normally when Redis is unavailable."""
    import redis.asyncio as aioredis

    if not channel_ids:
        return
    client: Any = None
    pubsub: Any = None
    try:
        client = aioredis.from_url(get_settings().redis_url)
        pubsub = client.pubsub()
        await pubsub.subscribe(*[channel_key(channel_id) for channel_id in channel_ids])
        yield "ready", {"channels": len(channel_ids)}
        while True:
            message = await pubsub.get_message(
                ignore_subscribe_messages=True,
                timeout=_HEARTBEAT_SECONDS,
            )
            if message is None:
                yield "ping", {}
                continue
            raw = message.get("data")
            if raw is None:
                continue
            channel_id = _channel_id(message.get("channel"))
            if authorize is not None and (not channel_id or not await authorize(channel_id)):
                logger.info("实时消息因成员权限已撤销而丢弃 channel=%s", channel_id)
                continue
            event = _event(raw)
            if event is not None:
                yield event
    except Exception:  # noqa: BLE001 - caller falls back to polling when Redis is unavailable
        logger.warning("实时订阅中断 channels=%s", channel_ids, exc_info=True)
    finally:
        await _close_safely(pubsub)
        await _close_safely(client)
