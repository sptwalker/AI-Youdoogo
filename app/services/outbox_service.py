"""Compatibility facade for platform outbox persistence operations."""

from app.platform.outbox.repository import (
    claim_next,
    complete,
    defer,
    enqueue,
    fail,
    renew_lease,
    utcnow,
)

__all__ = ["claim_next", "complete", "defer", "enqueue", "fail", "renew_lease", "utcnow"]
