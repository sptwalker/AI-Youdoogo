"""Ports that future relays, brokers, HTTP inboxes, and replay tools may implement."""

from datetime import datetime
from typing import Protocol

from app.platform.event_transport.contracts import (
    DeadLetterRecord,
    DeliveryFailure,
    EventEnvelope,
    InboxClaim,
    ReplayRequest,
)


class EventPublisher(Protocol):
    """Publish an already-constructed envelope with at-least-once semantics."""

    async def publish(self, envelope: EventEnvelope) -> None: ...


class EventInbox(Protocol):
    """Claim, complete, or release delivery attempts for idempotent consumers."""

    async def claim(
        self,
        envelope: EventEnvelope,
        *,
        consumer_id: str,
        claimed_at: datetime,
        lease_until: datetime,
    ) -> InboxClaim | None: ...

    async def complete(self, claim: InboxClaim, *, completed_at: datetime) -> bool: ...

    async def release(self, claim: InboxClaim, *, failure: DeliveryFailure) -> bool: ...


class DeadLetterStore(Protocol):
    """Retain terminal failures and their replay history."""

    async def put(
        self,
        failure: DeliveryFailure,
        *,
        stored_at: datetime,
    ) -> DeadLetterRecord: ...

    async def get(self, dead_letter_id: str) -> DeadLetterRecord | None: ...

    async def pending(self, *, limit: int = 100) -> tuple[DeadLetterRecord, ...]: ...

    async def record_replay(
        self,
        request: ReplayRequest,
        *,
        replayed_at: datetime,
    ) -> DeadLetterRecord: ...


class EventReplayer(Protocol):
    """Republish a retained envelope under an auditable replay request."""

    async def replay(self, request: ReplayRequest) -> EventEnvelope: ...
