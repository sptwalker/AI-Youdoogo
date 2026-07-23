"""Published Operational Analytics snapshots and results."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


class WorkbookParseFailure(Exception):
    """Public workbook validation failure mapped by delivery adapters."""


class AnalyticsConnectorFailure(Exception):
    """Public connector read failure mapped by delivery adapters."""


@dataclass(frozen=True, slots=True)
class DailyMetricSnapshot:
    stat_date: date
    product: str
    dau: int | None
    new_users: int | None
    retention_d1: float | None
    source: str

    def to_dict(self) -> dict[str, object]:
        return {
            "stat_date": self.stat_date.isoformat(),
            "product": self.product,
            "dau": self.dau,
            "new_users": self.new_users,
            "retention_d1": self.retention_d1,
        }


@dataclass(frozen=True, slots=True)
class IngestError:
    row_no: int
    field: str
    message: str

    def to_dict(self) -> dict[str, object]:
        return {"row_no": self.row_no, "field": self.field, "message": self.message}


@dataclass(frozen=True, slots=True)
class WorkbookIngestResult:
    template: str
    upserted: int
    duplicates: int
    errors: tuple[IngestError, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "template": self.template,
            "upserted": self.upserted,
            "duplicates": self.duplicates,
            "errors": [error.to_dict() for error in self.errors],
        }


@dataclass(frozen=True, slots=True)
class ThinkingDataSyncResult:
    stat_date: date
    upserted: int
    source: str = "thinkingdata"

    def to_dict(self) -> dict[str, object]:
        return {
            "date": self.stat_date.isoformat(),
            "upserted": self.upserted,
            "source": self.source,
        }


@dataclass(frozen=True, slots=True)
class ConnectorReadResult:
    status: str
    row_count: int
    sample: tuple[dict[str, object], ...]
    message: str

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "row_count": self.row_count,
            "sample": [dict(row) for row in self.sample],
            "msg": self.message,
        }


@dataclass(frozen=True, slots=True)
class EventAliasUpdate:
    view: str
    event_code: str
    display_name: str


@dataclass(frozen=True, slots=True)
class EventMetric:
    event_code: str
    count: int
    display_name: str

    def to_dict(self) -> dict[str, object]:
        return {
            "event_code": self.event_code,
            "count": self.count,
            "display_name": self.display_name,
        }


@dataclass(frozen=True, slots=True)
class EventViewSnapshot:
    view: str
    product: str
    events: tuple[EventMetric, ...]
    error: str | None = None

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "view": self.view,
            "product": self.product,
            "events": [event.to_dict() for event in self.events],
        }
        if self.error is not None:
            result["error"] = self.error
        return result
