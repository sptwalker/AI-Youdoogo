"""事件传输组装（docs/23 §3.2 + §6.3）：开关 on 时把 relay + 入站投影挂到路由扩展缝。"""

from __future__ import annotations

import logging

from app.bootstrap.workflow_events import (
    apply_step_completed,
    register_event_handler,
    unregister_event_handler,
)
from app.core.config import get_settings
from app.platform.eventing.inbox import register_inbox_projector, unregister_inbox_projector
from app.platform.eventing.relay import (
    build_relay_from_settings,
    build_step_ready_relay_from_settings,
)
from app.platform.eventing.remote_step import EXPERT_COMPLETED_EVENT, STEP_READY_EVENT

logger = logging.getLogger(__name__)


def register_relay() -> bool:
    """按配置注册出站 relay + 入站投影；默认关则不注册（现网零改变）。返回是否已启用。

    ``workflow.step.ready.v1`` 绑 StepReadyRelay（投递期注入回执令牌），其余类型绑通用 relay；
    并注册 ``expert.execution.completed.v1`` 入站投影（唤醒停车 step）。发送方即回执接收方，
    故随出站开关同装。
    """
    settings = get_settings()
    if not settings.event_relay_enabled:
        return False
    relay = build_relay_from_settings()
    step_ready_relay = build_step_ready_relay_from_settings()
    for event_type in settings.event_relay_event_types:
        handler = step_ready_relay if event_type == STEP_READY_EVENT else relay
        register_event_handler(event_type, handler)
    register_inbox_projector(EXPERT_COMPLETED_EVENT, apply_step_completed)
    logger.info(
        "event relay 已启用：peer=%s types=%s remote_steps=%s",
        settings.event_inbox_peer_url,
        list(settings.event_relay_event_types),
        list(settings.event_remote_step_skills),
    )
    return True


def unregister_relay() -> None:
    """卸载 relay handler + 入站投影（供关停/测试清理）。"""
    for event_type in get_settings().event_relay_event_types:
        unregister_event_handler(event_type)
    unregister_inbox_projector(EXPERT_COMPLETED_EVENT)
