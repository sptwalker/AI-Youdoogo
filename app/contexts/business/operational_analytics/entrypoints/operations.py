"""Request-scoped Operational Analytics operations."""

from __future__ import annotations

from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.business.operational_analytics.application.contracts import (
    AnalyticsConnectorConfiguration,
)
from app.contexts.business.operational_analytics.contracts import (
    ConnectorReadResult,
    DailyMetricSnapshot,
    EventAliasUpdate,
    EventViewSnapshot,
    ThinkingDataSyncResult,
    WorkbookIngestResult,
)
from app.contexts.business.operational_analytics.infrastructure.composition import (
    build_operational_analytics,
)
from app.contexts.business.operational_analytics.infrastructure.connector_adapter import (
    ThinkingDataAnalyticsConnector,
)


async def ingest_workbook(
    session: AsyncSession, content: bytes
) -> WorkbookIngestResult:
    return await build_operational_analytics(session).ingest_workbook(content)


async def sync_thinkingdata(
    session: AsyncSession, stat_date: date
) -> ThinkingDataSyncResult:
    return await build_operational_analytics(session).sync_thinkingdata(stat_date)


async def test_connector(
    session: AsyncSession, stat_date: date
) -> ConnectorReadResult:
    return await build_operational_analytics(session).test_connector(stat_date)


async def list_daily(
    session: AsyncSession, stat_date: date
) -> tuple[DailyMetricSnapshot, ...]:
    return await build_operational_analytics(session).list_daily(stat_date)


async def connector_configuration(
    session: AsyncSession,
) -> AnalyticsConnectorConfiguration:
    return await ThinkingDataAnalyticsConnector(session).configuration()


async def list_events(
    session: AsyncSession, stat_date: date
) -> tuple[EventViewSnapshot, ...]:
    return await build_operational_analytics(session).list_events(stat_date)


async def save_event_aliases(
    session: AsyncSession, updates: tuple[EventAliasUpdate, ...]
) -> int:
    return await build_operational_analytics(session).save_event_aliases(updates)
