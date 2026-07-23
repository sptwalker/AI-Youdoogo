"""Published commands, results, and events for Knowledge Indexing."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

INDEX_READY_V1 = "knowledge.index.ready.v1"
DOCUMENT_INDEX_REMOVED_V1 = "knowledge.index.removed.v1"


@dataclass(frozen=True, slots=True)
class IndexedDocument:
    id: uuid.UUID
    file_name: str
    knowledge_base_id: uuid.UUID
    category: str | None
    uploader_id: uuid.UUID
    storage_path: str
    file_size: int | None
    mime_type: str | None
    status: str
    create_time: datetime


@dataclass(frozen=True, slots=True)
class IndexTextCommand:
    title: str
    text: str
    uploader_id: uuid.UUID
    knowledge_base_id: uuid.UUID
    category: str | None = None
    document_id: uuid.UUID | None = None
    publish_events: bool = True


@dataclass(frozen=True, slots=True)
class IndexFileCommand:
    file_name: str
    content: bytes
    mime_type: str | None
    uploader_id: uuid.UUID
    knowledge_base_id: uuid.UUID
    category: str | None = None


@dataclass(frozen=True, slots=True)
class IndexFeishuDocumentCommand:
    document_id: str
    uploader_id: uuid.UUID
    knowledge_base_id: uuid.UUID
    category: str | None = None


@dataclass(frozen=True, slots=True)
class IndexReadyV1:
    event_id: uuid.UUID
    document_id: uuid.UUID
    knowledge_base_id: uuid.UUID
    index_version: int
    chunk_count: int
    scope: tuple[str, ...]
    occurred_at: datetime
    event_type: str = INDEX_READY_V1


@dataclass(frozen=True, slots=True)
class DocumentIndexRemovedV1:
    event_id: uuid.UUID
    document_id: uuid.UUID
    index_version: int
    occurred_at: datetime
    event_type: str = DOCUMENT_INDEX_REMOVED_V1
