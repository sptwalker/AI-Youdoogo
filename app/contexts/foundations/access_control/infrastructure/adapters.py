"""Adapters for Organization and Knowledge visibility providers."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.knowledge.wiki_management.public import (
    ancestor_department_ids,
    visible_knowledge_base_ids,
)


class LegacyDepartmentHierarchyAdapter:
    """Temporary adapter until Organization publishes its snapshot query."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def ancestors_of(self, department_id: uuid.UUID | None) -> tuple[uuid.UUID, ...]:
        return tuple(await ancestor_department_ids(self._session, department_id))


class LegacyKnowledgeVisibilityAdapter:
    """Translate Knowledge's current scope query behind a caller-owned port."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def visible_ids(
        self,
        *,
        department_id: uuid.UUID | None,
        is_admin: bool,
        extra_knowledge_ids: tuple[uuid.UUID, ...],
    ) -> tuple[uuid.UUID, ...]:
        ids = await visible_knowledge_base_ids(
            self._session,
            department_id=department_id,
            is_admin=is_admin,
            extra_knowledge_base_ids=list(extra_knowledge_ids),
        )
        return tuple(ids)


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class UUIDIdentifier:
    def new_id(self) -> uuid.UUID:
        return uuid.uuid4()
