"""Semantic Catalog application orchestration."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from app.contexts.foundations.knowledge.semantic_catalog.application.contracts import (
    CreateSemanticTerm,
    UpdateSemanticTerm,
)
from app.contexts.foundations.knowledge.semantic_catalog.application.ports import (
    SemanticCatalogUnitOfWork,
)
from app.contexts.foundations.knowledge.semantic_catalog.contracts import SemanticTermSnapshot
from app.contexts.foundations.knowledge.semantic_catalog.domain.models import (
    SemanticTerm,
    expand_terms,
    render_term_prompt,
)
from app.contexts.shared_kernel import ConflictDetected, ResourceNotFound, RuleViolation

UowFactory = Callable[[], SemanticCatalogUnitOfWork]


def _snapshot(term: SemanticTerm) -> SemanticTermSnapshot:
    return SemanticTermSnapshot(
        id=term.id,
        canonical_name=term.canonical_name,
        aliases=term.aliases,
        term_type=term.term_type,
        definition=term.definition,
        linked_view=term.linked_view,
        sql_template=term.sql_template,
        kb_refs=term.kb_refs,
        department_id=term.department_id,
    )


class SemanticCatalog:
    def __init__(self, uow_factory: UowFactory) -> None:
        self._uow_factory = uow_factory

    async def list(self) -> tuple[SemanticTermSnapshot, ...]:
        async with self._uow_factory() as uow:
            return tuple(_snapshot(term) for term in await uow.terms.list_active())

    async def expand_query(self, query: str) -> str:
        try:
            async with self._uow_factory() as uow:
                extra = expand_terms(query, await uow.terms.list_active())
        except Exception:  # noqa: BLE001 - optional semantic enrichment fails open
            return query
        return f"{query} {' '.join(extra)}" if extra else query

    async def term_prompt(self) -> str:
        try:
            async with self._uow_factory() as uow:
                return render_term_prompt(await uow.terms.list_active())
        except Exception:  # noqa: BLE001 - prompt enrichment must not block execution
            return ""

    async def create(self, command: CreateSemanticTerm) -> SemanticTermSnapshot:
        term = SemanticTerm(
            id=uuid.uuid4(),
            canonical_name=command.canonical_name,
            aliases=command.aliases,
            term_type=command.term_type,
            definition=command.definition,
            linked_view=command.linked_view,
            sql_template=command.sql_template,
            kb_refs=command.kb_refs,
            department_id=command.department_id,
        )
        term.validate()
        async with self._uow_factory() as uow:
            if await uow.terms.find_by_canonical(term.canonical_name) is not None:
                raise ConflictDetected("规范名已存在")
            await uow.terms.add(term)
            await uow.changes.publish(term)
            await uow.commit()
        return _snapshot(term)

    async def update(self, command: UpdateSemanticTerm) -> SemanticTermSnapshot:
        async with self._uow_factory() as uow:
            term = await uow.terms.get(command.term_id)
            if term is None:
                raise ResourceNotFound("术语不存在")
            if "canonical_name" in command.fields:
                term.canonical_name = (command.canonical_name or "").strip()
                if not term.canonical_name:
                    raise RuleViolation("规范名不能为空")
                clash = await uow.terms.find_by_canonical(term.canonical_name)
                if clash is not None and clash.id != term.id:
                    raise ConflictDetected("规范名已存在")
            if "aliases" in command.fields:
                term.aliases = command.aliases or ()
            if "kb_refs" in command.fields:
                term.kb_refs = command.kb_refs or ()
            mutable_fields = (
                "term_type",
                "definition",
                "linked_view",
                "sql_template",
                "department_id",
            )
            for field in mutable_fields:
                if field in command.fields:
                    setattr(term, field, getattr(command, field))
            term.validate()
            await uow.terms.save(term)
            await uow.changes.publish(term)
            await uow.commit()
            return _snapshot(term)

    async def delete(self, term_id: uuid.UUID) -> None:
        async with self._uow_factory() as uow:
            term = await uow.terms.get(term_id)
            if term is None:
                raise ResourceNotFound("术语不存在")
            await uow.terms.soft_delete(term_id)
            await uow.changes.publish(term)
            await uow.commit()
