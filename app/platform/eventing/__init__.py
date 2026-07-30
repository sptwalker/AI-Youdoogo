"""事件传输平台模块（Phase 3 硬前置门禁 / docs/23）：Outbox Relay + 幂等 Inbox。

注意：本 __init__ 只暴露"轻"符号（ORM / 线协议 / relay），**不**在此 re-export
``composition``——它导入 ``app.bootstrap``，而 ``app.models`` 会导入本包，经此再入 bootstrap
会形成 import cycle。装配侧请直接 ``from app.platform.eventing.composition import register_relay``。
"""

from app.platform.eventing.inbox import EventEnvelope, process_pending, receive_event
from app.platform.eventing.inbox_model import (
    INBOX_PROCESSED,
    INBOX_RECEIVED,
    InboxEvent,
)
from app.platform.eventing.relay import EVENTS_SCOPE, HttpInboxRelay, build_relay_from_settings

__all__ = [
    "EVENTS_SCOPE",
    "EventEnvelope",
    "HttpInboxRelay",
    "INBOX_PROCESSED",
    "INBOX_RECEIVED",
    "InboxEvent",
    "build_relay_from_settings",
    "process_pending",
    "receive_event",
]
