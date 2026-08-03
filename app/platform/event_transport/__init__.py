"""Dormant reliable-event contracts and in-memory verification adapters."""

from app.platform.event_transport.contracts import (
    DeadLetterRecord,
    DeliveryFailure,
    EventEnvelope,
    InboxClaim,
    JSONScalar,
    JSONValue,
    ReplayRequest,
)
from app.platform.event_transport.memory import (
    InMemoryDeadLetterStore,
    InMemoryEventInbox,
    InMemoryEventPublisher,
    InMemoryEventReplayer,
)
from app.platform.event_transport.ports import (
    DeadLetterStore,
    EventInbox,
    EventPublisher,
    EventReplayer,
)

__all__ = [
    "DeadLetterRecord",
    "DeadLetterStore",
    "DeliveryFailure",
    "EventEnvelope",
    "EventInbox",
    "EventPublisher",
    "EventReplayer",
    "InMemoryDeadLetterStore",
    "InMemoryEventInbox",
    "InMemoryEventPublisher",
    "InMemoryEventReplayer",
    "InboxClaim",
    "JSONScalar",
    "JSONValue",
    "ReplayRequest",
]
