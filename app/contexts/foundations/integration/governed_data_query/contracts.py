"""Published language for catalog discovery and governed read-only queries."""

from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CatalogSource:
    name: str
    code: str
    is_active: bool

    def to_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "code": self.code,
            "active": "是" if self.is_active else "否",
        }


@dataclass(frozen=True, slots=True)
class NamedEvent:
    event_code: str
    display_name: str

    def to_dict(self) -> dict[str, str]:
        return {"event_code": self.event_code, "display_name": self.display_name}


@dataclass(frozen=True, slots=True)
class CatalogView:
    view: str
    product: str
    named_events: tuple[NamedEvent, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "view": self.view,
            "product": self.product,
            "named_events": [event.to_dict() for event in self.named_events],
        }


@dataclass(frozen=True, slots=True)
class DataCatalogSnapshot:
    sources: tuple[CatalogSource, ...]
    views: tuple[CatalogView, ...]

    @property
    def allowed_views(self) -> frozenset[str]:
        return frozenset(view.view.lower() for view in self.views)

    def to_dict(self) -> dict[str, object]:
        return {
            "sources": [source.to_dict() for source in self.sources],
            "views": [view.to_dict() for view in self.views],
        }


@dataclass(frozen=True, slots=True)
class GovernedQueryRequest:
    sql: str
    actor_id: uuid.UUID | None
    actor_role: str | None
    source: str = "agent"


@dataclass(frozen=True, slots=True)
class GovernedQueryResult:
    status: str
    columns: tuple[str, ...] = ()
    rows: tuple[dict[str, object], ...] = ()
    row_count: int = 0
    truncated: bool = False
    reason: str | None = None
    message: str | None = None

    def to_dict(self) -> dict[str, object]:
        if self.status == "rejected":
            return {"status": self.status, "reason": self.reason or ""}
        if self.status == "fail":
            return {"status": self.status, "msg": self.message or ""}
        return {
            "status": self.status,
            "columns": list(self.columns),
            "rows": [dict(row) for row in self.rows],
            "row_count": self.row_count,
            "truncated": self.truncated,
        }
