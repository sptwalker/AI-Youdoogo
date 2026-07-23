"""SQLAlchemy implementation of Semantic Catalog ports."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from types import TracebackType

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.knowledge.semantic_catalog.application.ports import (
    SemanticChangePublisher,
    SemanticTermRepository,
)
from app.contexts.foundations.knowledge.semantic_catalog.domain.models import SemanticTerm
from app.models.semantic_term import SemanticTerm as SemanticTermRow
from app.platform.outbox.source_change import publish_source_change


def _to_domain(row: SemanticTermRow) -> SemanticTerm:
    return SemanticTerm(
        id=row.id,
        canonical_name=row.canonical_name,
        aliases=tuple(row.aliases or ()),
        term_type=row.term_type,
        definition=row.definition,
        linked_view=row.linked_view,
        sql_template=row.sql_template,
        kb_refs=tuple(row.kb_refs or ()),
        department_id=row.department_id,
    )


class SqlAlchemySemanticTermRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_active(self) -> Sequence[SemanticTerm]:
        statement = (
            select(SemanticTermRow)
            .where(SemanticTermRow.is_delete.is_(False))
            .order_by(SemanticTermRow.term_type, SemanticTermRow.canonical_name)
        )
        return tuple(_to_domain(row) for row in (await self._session.execute(statement)).scalars())

    async def get(self, term_id: uuid.UUID) -> SemanticTerm | None:
        row = await self._session.get(SemanticTermRow, term_id)
        if row is None or row.is_delete:
            return None
        return _to_domain(row)

    async def find_by_canonical(self, name: str) -> SemanticTerm | None:
        statement = select(SemanticTermRow).where(
            SemanticTermRow.canonical_name == name,
            SemanticTermRow.is_delete.is_(False),
        )
        row = (await self._session.execute(statement)).scalar_one_or_none()
        return _to_domain(row) if row is not None else None

    async def add(self, term: SemanticTerm) -> None:
        self._session.add(
            SemanticTermRow(
                id=term.id,
                canonical_name=term.canonical_name,
                aliases=list(term.aliases),
                term_type=term.term_type,
                definition=term.definition,
                linked_view=term.linked_view,
                sql_template=term.sql_template,
                kb_refs=list(term.kb_refs),
                department_id=term.department_id,
            )
        )
        await self._session.flush()

    async def save(self, term: SemanticTerm) -> None:
        row = await self._session.get(SemanticTermRow, term.id)
        if row is None:
            raise LookupError(term.id)
        row.canonical_name = term.canonical_name
        row.aliases = list(term.aliases)
        row.term_type = term.term_type
        row.definition = term.definition
        row.linked_view = term.linked_view
        row.sql_template = term.sql_template
        row.kb_refs = list(term.kb_refs)
        row.department_id = term.department_id
        await self._session.flush()

    async def soft_delete(self, term_id: uuid.UUID) -> None:
        row = await self._session.get(SemanticTermRow, term_id)
        if row is None:
            raise LookupError(term_id)
        row.is_delete = True
        await self._session.flush()


class SqlAlchemySemanticChangePublisher:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def publish(self, term: SemanticTerm) -> None:
        scopes = ["semantic_catalog"]
        if term.department_id is not None:
            scopes.append(f"department:{term.department_id}")
        await publish_source_change(
            self._session,
            source_type="semantic_term",
            source_id=term.id,
            affected_scopes=tuple(scopes),
        )


class SqlAlchemySemanticCatalogUnitOfWork:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self.terms: SemanticTermRepository = SqlAlchemySemanticTermRepository(session)
        self.changes: SemanticChangePublisher = SqlAlchemySemanticChangePublisher(session)

    async def __aenter__(self) -> SqlAlchemySemanticCatalogUnitOfWork:
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
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()
