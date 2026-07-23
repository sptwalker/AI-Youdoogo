"""Ports owned by Operational Analytics application policy."""

from __future__ import annotations

from datetime import date
from types import TracebackType
from typing import Protocol, Self

from app.contexts.business.operational_analytics.application.contracts import (
    AnalyticsConnectorConfiguration,
    ParsedWorkbook,
)
from app.contexts.business.operational_analytics.contracts import (
    AnalyticsConnectorFailure,
    DailyMetricSnapshot,
    EventAliasUpdate,
)
from app.contexts.business.operational_analytics.domain.models import DailyMetricUpsert

ConnectorReadFailure = AnalyticsConnectorFailure


class WorkbookParserPort(Protocol):
    def parse(self, content: bytes) -> ParsedWorkbook: ...


class AnalyticsConnectorPort(Protocol):
    async def configuration(self) -> AnalyticsConnectorConfiguration: ...

    async def query(self, sql: str) -> list[dict[str, object]]: ...


class DailyMetricRepository(Protocol):
    async def upsert(self, metric: DailyMetricUpsert) -> None: ...

    async def list_for_date(self, stat_date: date) -> tuple[DailyMetricSnapshot, ...]: ...


class EventAliasRepository(Protocol):
    async def aliases_for(self, view: str) -> dict[str, str]: ...

    async def save(self, updates: tuple[EventAliasUpdate, ...]) -> int: ...


class OperationalAnalyticsUnitOfWork(Protocol):
    metrics: DailyMetricRepository
    aliases: EventAliasRepository

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...
