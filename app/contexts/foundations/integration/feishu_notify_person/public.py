"""Stable feishu_notify_person operations for external callers (cross-Context orchestration)."""

from app.contexts.foundations.integration.feishu_notify_person.entrypoints.operations import (
    feishu_notify_person_available,
    send_to_recipient,
)

__all__ = [
    "feishu_notify_person_available",
    "send_to_recipient",
]
