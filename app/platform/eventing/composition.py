"""事件传输组装（docs/23 §3.2）：开关 on 时把 relay 挂到 outbox 路由扩展缝。"""

from __future__ import annotations

import logging

from app.bootstrap.workflow_events import register_event_handler, unregister_event_handler
from app.core.config import get_settings
from app.platform.eventing.relay import build_relay_from_settings

logger = logging.getLogger(__name__)


def register_relay() -> bool:
    """按配置注册出站 relay handler；默认关则不注册（现网零改变）。返回是否已启用。"""
    settings = get_settings()
    if not settings.event_relay_enabled:
        return False
    relay = build_relay_from_settings()
    for event_type in settings.event_relay_event_types:
        register_event_handler(event_type, relay)
    logger.info(
        "event relay 已启用：peer=%s types=%s",
        settings.event_inbox_peer_url,
        list(settings.event_relay_event_types),
    )
    return True


def unregister_relay() -> None:
    """卸载 relay handler（供关停/测试清理）。"""
    for event_type in get_settings().event_relay_event_types:
        unregister_event_handler(event_type)
