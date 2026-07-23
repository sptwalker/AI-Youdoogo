"""Commands accepted by Wiki Management use cases."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.contexts.foundations.knowledge.wiki_management.contracts import KnowledgeScope


@dataclass(frozen=True, slots=True)
class CreateKnowledgeBase:
    name: str
    scope: KnowledgeScope
    code: str | None = None
    department_id: uuid.UUID | None = None
    owner_agent_id: uuid.UUID | None = None
    is_confidential: bool = False
    description: str | None = None


@dataclass(frozen=True, slots=True)
class UpdateKnowledgeBase:
    knowledge_base_id: uuid.UUID
    name: str | None = None
    is_confidential: bool | None = None
    description: str | None = None
    is_active: bool | None = None
    department_id: uuid.UUID | None = None
