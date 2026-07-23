"""Semantic Catalog persistence ports."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from types import TracebackType
from typing import Protocol, Self

from app.contexts.foundations.knowledge.semantic_catalog.domain.models import SemanticTerm


class SemanticTermRepository(Protocol):
    async def list_active(self) -> Sequence[SemanticTerm]: ...

    async def get(self, term_id: uuid.UUID) -> SemanticTerm | None: ...

    async def find_by_canonical(self, name: str) -> SemanticTerm | None: ...

    async def add(self, term: SemanticTerm) -> None: ...

    async def save(self, term: SemanticTerm) -> None: ...

    async def soft_delete(self, term_id: uuid.UUID) -> None: ...


class SemanticChangePublisher(Protocol):
    async def publish(self, term: SemanticTerm) -> None: ...


class SemanticCatalogUnitOfWork(Protocol):
    terms: SemanticTermRepository
    changes: SemanticChangePublisher

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...
