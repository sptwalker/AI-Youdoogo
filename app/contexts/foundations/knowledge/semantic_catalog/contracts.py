"""Published Semantic Catalog contracts."""

from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SemanticTermSnapshot:
    id: uuid.UUID
    canonical_name: str
    aliases: tuple[str, ...]
    term_type: str
    definition: str | None
    linked_view: str | None
    sql_template: str | None
    kb_refs: tuple[str, ...]
    department_id: uuid.UUID | None

    def to_dict(self) -> dict[str, object]:
        return {
            "id": str(self.id),
            "canonical_name": self.canonical_name,
            "aliases": list(self.aliases),
            "term_type": self.term_type,
            "definition": self.definition,
            "linked_view": self.linked_view,
            "sql_template": self.sql_template,
            "kb_refs": list(self.kb_refs),
            "department_id": str(self.department_id) if self.department_id else None,
        }


@dataclass(frozen=True, slots=True)
class ResolveSemanticQuery:
    query: str


@dataclass(frozen=True, slots=True)
class ResolvedSemanticQuery:
    original: str
    expanded: str
    matched_terms: tuple[str, ...]
