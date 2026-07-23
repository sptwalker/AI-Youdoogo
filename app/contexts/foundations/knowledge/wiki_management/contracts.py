"""Published language for Wiki Management."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

DOCUMENT_PUBLISHED_V1 = "knowledge.document.published.v1"
DOCUMENT_ARCHIVED_V1 = "knowledge.document.archived.v1"


class KnowledgeScope(StrEnum):
    COMPANY = "company"
    DEPARTMENT = "department"
    PERSONAL = "personal"


@dataclass(frozen=True, slots=True)
class KnowledgeBaseSnapshot:
    id: uuid.UUID
    name: str
    code: str
    scope: KnowledgeScope
    department_id: uuid.UUID | None
    owner_agent_id: uuid.UUID | None
    is_confidential: bool
    is_default: bool
    is_active: bool
    description: str | None
    file_count: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "id": str(self.id),
            "name": self.name,
            "code": self.code,
            "scope": self.scope.value,
            "department_id": str(self.department_id) if self.department_id else None,
            "owner_agent_id": str(self.owner_agent_id) if self.owner_agent_id else None,
            "is_confidential": self.is_confidential,
            "is_default": self.is_default,
            "is_active": self.is_active,
            "description": self.description,
            "file_count": self.file_count,
        }


@dataclass(frozen=True, slots=True)
class DocumentSnapshot:
    id: uuid.UUID
    knowledge_base_id: uuid.UUID
    file_name: str
    category: str | None
    uploader_id: uuid.UUID
    storage_path: str
    file_size: int | None
    mime_type: str | None
    status: str
    source_version: int


@dataclass(frozen=True, slots=True)
class DocumentPublishedV1:
    event_id: uuid.UUID
    document: DocumentSnapshot
    scope: tuple[str, ...]
    occurred_at: datetime
    event_type: str = DOCUMENT_PUBLISHED_V1


@dataclass(frozen=True, slots=True)
class DocumentArchivedV1:
    event_id: uuid.UUID
    document_id: uuid.UUID
    knowledge_base_id: uuid.UUID
    source_version: int
    scope: tuple[str, ...]
    occurred_at: datetime
    event_type: str = DOCUMENT_ARCHIVED_V1
