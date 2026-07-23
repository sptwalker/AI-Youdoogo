"""SQLAlchemy persistence for Wiki Management using the existing tables."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from types import TracebackType

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.knowledge.wiki_management.application.ports import (
    KnowledgeBaseRepository,
    KnowledgeChangePublisher,
)
from app.contexts.foundations.knowledge.wiki_management.contracts import KnowledgeScope
from app.contexts.foundations.knowledge.wiki_management.domain.models import KnowledgeBase
from app.contexts.shared_kernel import ConflictDetected
from app.models.knowledge import KnowledgeBase as KnowledgeBaseRow
from app.models.knowledge import KnowledgeFile
from app.platform.outbox.source_change import publish_source_change


def _to_domain(row: KnowledgeBaseRow) -> KnowledgeBase:
    return KnowledgeBase(
        id=row.id,
        name=row.name,
        code=row.code,
        scope=KnowledgeScope(row.scope),
        department_id=row.department_id,
        owner_agent_id=row.owner_agent_id,
        is_confidential=row.is_confidential,
        is_default=row.is_default,
        is_active=row.is_active,
        description=row.description,
    )


class SqlAlchemyKnowledgeBaseRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, knowledge_base_id: uuid.UUID) -> KnowledgeBase | None:
        row = await self._session.get(KnowledgeBaseRow, knowledge_base_id)
        if row is None or row.is_delete:
            return None
        return _to_domain(row)

    async def get_default(self) -> KnowledgeBase | None:
        statement = select(KnowledgeBaseRow).where(
            KnowledgeBaseRow.is_default.is_(True),
            KnowledgeBaseRow.is_delete.is_(False),
        )
        row = (await self._session.execute(statement)).scalar_one_or_none()
        return _to_domain(row) if row is not None else None

    async def code_exists(self, code: str, *, excluding_id: uuid.UUID | None = None) -> bool:
        statement = select(KnowledgeBaseRow.id).where(
            KnowledgeBaseRow.code == code,
            KnowledgeBaseRow.is_delete.is_(False),
        )
        if excluding_id is not None:
            statement = statement.where(KnowledgeBaseRow.id != excluding_id)
        return (await self._session.execute(statement)).scalar_one_or_none() is not None

    async def document_count(self, knowledge_base_id: uuid.UUID) -> int:
        statement = (
            select(func.count())
            .select_from(KnowledgeFile)
            .where(
                KnowledgeFile.knowledge_base_id == knowledge_base_id,
                KnowledgeFile.is_delete.is_(False),
            )
        )
        return int((await self._session.execute(statement)).scalar_one())

    async def list_records(self) -> Sequence[tuple[KnowledgeBase, int]]:
        counts = {
            knowledge_base_id: int(count)
            for knowledge_base_id, count in (
                await self._session.execute(
                    select(KnowledgeFile.knowledge_base_id, func.count())
                    .where(KnowledgeFile.is_delete.is_(False))
                    .group_by(KnowledgeFile.knowledge_base_id)
                )
            ).all()
        }
        statement = (
            select(KnowledgeBaseRow)
            .where(KnowledgeBaseRow.is_delete.is_(False))
            .order_by(KnowledgeBaseRow.is_default.desc(), KnowledgeBaseRow.create_time)
        )
        rows = list((await self._session.execute(statement)).scalars())
        return tuple((_to_domain(row), counts.get(row.id, 0)) for row in rows)

    async def add(self, knowledge_base: KnowledgeBase) -> None:
        self._session.add(
            KnowledgeBaseRow(
                id=knowledge_base.id,
                name=knowledge_base.name,
                code=knowledge_base.code,
                scope=knowledge_base.scope.value,
                department_id=knowledge_base.department_id,
                owner_agent_id=knowledge_base.owner_agent_id,
                is_confidential=knowledge_base.is_confidential,
                is_default=knowledge_base.is_default,
                is_active=knowledge_base.is_active,
                description=knowledge_base.description,
            )
        )
        await self._session.flush()

    async def save(self, knowledge_base: KnowledgeBase) -> None:
        row = await self._session.get(KnowledgeBaseRow, knowledge_base.id)
        if row is None:
            raise LookupError(knowledge_base.id)
        row.name = knowledge_base.name
        row.code = knowledge_base.code
        row.scope = knowledge_base.scope.value
        row.department_id = knowledge_base.department_id
        row.owner_agent_id = knowledge_base.owner_agent_id
        row.is_confidential = knowledge_base.is_confidential
        row.is_default = knowledge_base.is_default
        row.is_active = knowledge_base.is_active
        row.description = knowledge_base.description
        await self._session.flush()

    async def soft_delete(self, knowledge_base_id: uuid.UUID) -> None:
        row = await self._session.get(KnowledgeBaseRow, knowledge_base_id)
        if row is None:
            raise LookupError(knowledge_base_id)
        row.is_delete = True
        await self._session.flush()


class SqlAlchemyKnowledgeChangePublisher:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def publish(self, knowledge_base: KnowledgeBase) -> None:
        scope = ["knowledge", knowledge_base.scope.value]
        if knowledge_base.department_id is not None:
            scope.append(f"department:{knowledge_base.department_id}")
        if knowledge_base.owner_agent_id is not None:
            scope.append(f"agent:{knowledge_base.owner_agent_id}")
        await publish_source_change(
            self._session,
            source_type="knowledge_base",
            source_id=knowledge_base.id,
            affected_scopes=tuple(scope),
        )


class SqlAlchemyWikiUnitOfWork:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self.knowledge_bases: KnowledgeBaseRepository = SqlAlchemyKnowledgeBaseRepository(session)
        self.changes: KnowledgeChangePublisher = SqlAlchemyKnowledgeChangePublisher(session)

    async def __aenter__(self) -> SqlAlchemyWikiUnitOfWork:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if exc_type is not None:
            await self.rollback()

    async def commit(self) -> None:
        try:
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            raise ConflictDetected("知识库编码已存在") from exc

    async def rollback(self) -> None:
        await self._session.rollback()
