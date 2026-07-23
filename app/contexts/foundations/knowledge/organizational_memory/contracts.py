"""Published Organizational Memory contracts."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import StrEnum


class MemoryKind(StrEnum):
    SUMMARY = "summary"
    FACT = "fact"
    PREFERENCE = "preference"
    DECISION = "decision"
    INFERENCE = "inference"


@dataclass(frozen=True, slots=True)
class DistillConversationCommand:
    transcript: str
    principal_id: uuid.UUID | None = None
    source_type: str = "conversation"
    source_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class MemoryDraft:
    content: str
    source_type: str
    source_id: uuid.UUID | None
    kind: MemoryKind = MemoryKind.SUMMARY
    confidence: float = 1.0
    model_generated: bool = True
