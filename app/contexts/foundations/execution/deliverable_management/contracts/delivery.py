"""Framework-independent Deliverable Management contracts."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class DeliverableFormat(StrEnum):
    CSV = "csv"
    XLSX = "xlsx"
    MARKDOWN = "md"
    TEXT = "txt"


@dataclass(frozen=True, slots=True)
class PublishDeliverableCommand:
    owner_user_id: uuid.UUID
    agent_id: uuid.UUID | None
    agent_name: str
    name: str
    file_format: DeliverableFormat
    body: str
    idempotency_key: str | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("deliverable name is required")
        if not self.body.strip():
            raise ValueError("deliverable body is required")
        if len(self.name) > 120:
            raise ValueError("deliverable name exceeds 120 characters")


@dataclass(frozen=True, slots=True)
class PublishedArtifact:
    deliverable_id: uuid.UUID
    file_name: str
    file_format: DeliverableFormat
    storage_path: str
    file_size: int
    agent_name: str

    def to_reference(self) -> dict[str, str | int]:
        return {
            "deliverable_id": str(self.deliverable_id),
            "file_name": self.file_name,
            "file_format": self.file_format.value,
            "storage_path": self.storage_path,
            "file_size": self.file_size,
            "agent_name": self.agent_name,
        }


@dataclass(frozen=True, slots=True)
class DeliverableSnapshot:
    deliverable_id: uuid.UUID
    owner_user_id: uuid.UUID
    agent_name: str
    file_name: str
    file_format: DeliverableFormat
    storage_path: str
    file_size: int
    create_time: datetime
    is_deleted: bool
