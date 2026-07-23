"""Semantic Catalog commands."""

from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CreateSemanticTerm:
    canonical_name: str
    aliases: tuple[str, ...] = ()
    term_type: str = "metric"
    definition: str | None = None
    linked_view: str | None = None
    sql_template: str | None = None
    kb_refs: tuple[str, ...] = ()
    department_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class UpdateSemanticTerm:
    term_id: uuid.UUID
    canonical_name: str | None = None
    aliases: tuple[str, ...] | None = None
    term_type: str | None = None
    definition: str | None = None
    linked_view: str | None = None
    sql_template: str | None = None
    kb_refs: tuple[str, ...] | None = None
    department_id: uuid.UUID | None = None
    fields: frozenset[str] = frozenset()
