"""Policy-owned persistence and event ports for Wiki Management."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from types import TracebackType
from typing import Protocol, Self

from app.contexts.foundations.knowledge.wiki_management.domain.models import KnowledgeBase


class KnowledgeBaseRepository(Protocol):
    async def get(self, knowledge_base_id: uuid.UUID) -> KnowledgeBase | None: ...

    async def get_default(self) -> KnowledgeBase | None: ...

    async def code_exists(self, code: str, *, excluding_id: uuid.UUID | None = None) -> bool: ...

    async def document_count(self, knowledge_base_id: uuid.UUID) -> int: ...

    async def list_records(self) -> Sequence[tuple[KnowledgeBase, int]]: ...

    async def add(self, knowledge_base: KnowledgeBase) -> None: ...

    async def save(self, knowledge_base: KnowledgeBase) -> None: ...

    async def soft_delete(self, knowledge_base_id: uuid.UUID) -> None: ...


class KnowledgeChangePublisher(Protocol):
    async def publish(self, knowledge_base: KnowledgeBase) -> None: ...


class WikiUnitOfWork(Protocol):
    knowledge_bases: KnowledgeBaseRepository
    changes: KnowledgeChangePublisher

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...
