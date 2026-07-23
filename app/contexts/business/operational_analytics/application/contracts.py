"""Application-owned parser and connector contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.contexts.business.operational_analytics.contracts import IngestError


@dataclass(frozen=True, slots=True)
class ParsedMetricRow:
    stat_date: date
    product: str
    dau: int | None
    new_users: int | None
    retention_d1: float | None


@dataclass(frozen=True, slots=True)
class ParsedWorkbook:
    template: str
    rows: tuple[ParsedMetricRow, ...]
    errors: tuple[IngestError, ...]
    duplicate_count: int


@dataclass(frozen=True, slots=True)
class AnalyticsConnectorConfiguration:
    base_url: str
    api_secret: str
    sql_template: str
    mapping: dict[str, str]
    event_views: tuple[tuple[str, str], ...]
