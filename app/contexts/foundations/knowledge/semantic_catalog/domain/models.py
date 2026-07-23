"""Framework-independent semantic term model and policies."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from app.contexts.shared_kernel import RuleViolation

MAX_PROMPT_TERMS = 60
MAX_EXPAND_TERMS = 8


class TermView(Protocol):
    @property
    def canonical_name(self) -> str: ...

    @property
    def aliases(self) -> Sequence[str]: ...

    @property
    def term_type(self) -> str: ...

    @property
    def definition(self) -> str | None: ...

    @property
    def linked_view(self) -> str | None: ...


@dataclass(slots=True)
class SemanticTerm:
    id: uuid.UUID
    canonical_name: str
    aliases: tuple[str, ...] = ()
    term_type: str = "metric"
    definition: str | None = None
    linked_view: str | None = None
    sql_template: str | None = None
    kb_refs: tuple[str, ...] = ()
    department_id: uuid.UUID | None = None

    def validate(self) -> None:
        self.canonical_name = self.canonical_name.strip()
        if not self.canonical_name:
            raise RuleViolation("规范名必填")
        self.aliases = tuple(alias.strip() for alias in self.aliases if alias.strip())
        self.kb_refs = tuple(reference.strip() for reference in self.kb_refs if reference.strip())


def expand_terms(query: str, terms: Sequence[TermView]) -> tuple[str, ...]:
    if not query.strip():
        return ()
    extra: list[str] = []
    seen: set[str] = set()
    for term in terms:
        names = [term.canonical_name, *term.aliases]
        if not any(name and name in query for name in names):
            continue
        for name in names:
            if name and name not in query and name not in seen:
                seen.add(name)
                extra.append(name)
                if len(extra) >= MAX_EXPAND_TERMS:
                    return tuple(extra)
    return tuple(extra)


def render_term_prompt(terms: Sequence[TermView]) -> str:
    if not terms:
        return ""
    lines = ["\n\n【业务术语】（公司统一口径，回答/取数时以此为准，别名视同规范名）:"]
    type_names = {"metric": "指标", "dimension": "维度", "entity": "实体"}
    for term in terms[:MAX_PROMPT_TERMS]:
        parts = [f"- {term.canonical_name}（{type_names.get(term.term_type, term.term_type)}）"]
        if term.aliases:
            parts.append("别名:" + "、".join(term.aliases))
        if term.definition:
            parts.append(f"口径:{term.definition}")
        if term.linked_view:
            parts.append(f"数据源:{term.linked_view}")
        lines.append("；".join(parts))
    return "\n".join(lines)
