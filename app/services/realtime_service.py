"""Compatibility exports for the Platform realtime transport."""

from app.platform.realtime import Event, channel_key, publish, subscribe

__all__ = ["Event", "channel_key", "publish", "subscribe"]
