"""Validation handler for versioned Knowledge integration facts."""

from __future__ import annotations

from typing import Any, Protocol

from app.contexts.foundations.knowledge.knowledge_indexing.contracts import (
    DOCUMENT_INDEX_REMOVED_V1,
    INDEX_READY_V1,
)
from app.contexts.foundations.knowledge.wiki_management.contracts import (
    DOCUMENT_ARCHIVED_V1,
    DOCUMENT_PUBLISHED_V1,
)

KNOWLEDGE_EVENT_TYPES = frozenset(
    {
        DOCUMENT_PUBLISHED_V1,
        DOCUMENT_ARCHIVED_V1,
        INDEX_READY_V1,
        DOCUMENT_INDEX_REMOVED_V1,
    }
)


class KnowledgeEventEnvelope(Protocol):
    event_type: str
    payload: dict[str, Any]


def handles(event_type: str) -> bool:
    return event_type in KNOWLEDGE_EVENT_TYPES


async def handle(event: KnowledgeEventEnvelope) -> None:
    """Validate published facts before the shared worker marks them complete.

    Indexing is synchronous during this schema-preserving migration. These durable
    facts are consumed for validation/audit today and remain replayable contracts
    for a later asynchronous projection without changing producers.
    """
    if not handles(event.event_type):
        raise ValueError(f"unsupported knowledge event: {event.event_type}")
    if not event.payload.get("event_id") or not event.payload.get("document_id"):
        raise ValueError("knowledge event is missing identity")
    version = event.payload.get("source_version") or event.payload.get("index_version")
    if not isinstance(version, int) or version <= 0:
        raise ValueError("knowledge event is missing a positive version")
