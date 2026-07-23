"""Request-scoped Semantic Catalog operations."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.knowledge.semantic_catalog.application.contracts import (
    CreateSemanticTerm,
    UpdateSemanticTerm,
)
from app.contexts.foundations.knowledge.semantic_catalog.application.use_cases import (
    SemanticCatalog,
)
from app.contexts.foundations.knowledge.semantic_catalog.contracts import SemanticTermSnapshot
from app.contexts.foundations.knowledge.semantic_catalog.infrastructure.sqlalchemy import (
    SqlAlchemySemanticCatalogUnitOfWork,
)


def _catalog(session: AsyncSession) -> SemanticCatalog:
    return SemanticCatalog(lambda: SqlAlchemySemanticCatalogUnitOfWork(session))


def _strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(item) for item in value)


def _optional_uuid(value: object) -> uuid.UUID | None:
    return value if isinstance(value, uuid.UUID) else None


async def list_terms(session: AsyncSession) -> tuple[SemanticTermSnapshot, ...]:
    return await _catalog(session).list()


async def expand_query(session: AsyncSession, query: str) -> str:
    return await _catalog(session).expand_query(query)


async def term_prompt(session: AsyncSession) -> str:
    return await _catalog(session).term_prompt()


async def create_term(session: AsyncSession, data: dict[str, object]) -> SemanticTermSnapshot:
    return await _catalog(session).create(
        CreateSemanticTerm(
            canonical_name=str(data.get("canonical_name") or ""),
            aliases=_strings(data.get("aliases")),
            term_type=str(data.get("term_type") or "metric"),
            definition=str(data["definition"]) if data.get("definition") else None,
            linked_view=str(data["linked_view"]) if data.get("linked_view") else None,
            sql_template=str(data["sql_template"]) if data.get("sql_template") else None,
            kb_refs=_strings(data.get("kb_refs")),
            department_id=_optional_uuid(data.get("department_id")),
        )
    )


async def update_term(
    session: AsyncSession, term_id: uuid.UUID, data: dict[str, object]
) -> SemanticTermSnapshot:
    aliases_value = data.get("aliases")
    kb_refs_value = data.get("kb_refs")
    department_value = data.get("department_id")
    return await _catalog(session).update(
        UpdateSemanticTerm(
            term_id=term_id,
            canonical_name=str(data.get("canonical_name") or "")
            if "canonical_name" in data
            else None,
            aliases=_strings(aliases_value) if "aliases" in data else None,
            term_type=str(data.get("term_type")) if data.get("term_type") else None,
            definition=str(data.get("definition")) if data.get("definition") else None,
            linked_view=str(data.get("linked_view")) if data.get("linked_view") else None,
            sql_template=str(data.get("sql_template")) if data.get("sql_template") else None,
            kb_refs=_strings(kb_refs_value) if "kb_refs" in data else None,
            department_id=_optional_uuid(department_value),
            fields=frozenset(data),
        )
    )


async def delete_term(session: AsyncSession, term_id: uuid.UUID) -> None:
    await _catalog(session).delete(term_id)
