"""Operational Analytics ingestion, synchronization, and query use cases."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from app.contexts.business.operational_analytics.application.ports import (
    AnalyticsConnectorPort,
    ConnectorReadFailure,
    OperationalAnalyticsUnitOfWork,
    WorkbookParserPort,
)
from app.contexts.business.operational_analytics.contracts import (
    ConnectorReadResult,
    DailyMetricSnapshot,
    EventAliasUpdate,
    EventMetric,
    EventViewSnapshot,
    ThinkingDataSyncResult,
    WorkbookIngestResult,
)
from app.contexts.business.operational_analytics.domain.models import DailyMetricUpsert
from app.contexts.shared_kernel import RuleViolation

UowFactory = Callable[[], OperationalAnalyticsUnitOfWork]


def _event_count(value: object) -> int:
    if isinstance(value, (int, float, str)):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


class OperationalAnalytics:
    def __init__(
        self,
        uow_factory: UowFactory,
        *,
        parser: WorkbookParserPort,
        connector: AnalyticsConnectorPort,
    ) -> None:
        self._uow_factory = uow_factory
        self._parser = parser
        self._connector = connector

    async def ingest_workbook(self, content: bytes) -> WorkbookIngestResult:
        parsed = self._parser.parse(content)
        async with self._uow_factory() as uow:
            for row in parsed.rows:
                metric = DailyMetricUpsert(
                    stat_date=row.stat_date,
                    product=row.product,
                    source="excel",
                    fields={
                        "dau": row.dau,
                        "new_users": row.new_users,
                        "retention_d1": row.retention_d1,
                    },
                )
                metric.validate()
                await uow.metrics.upsert(metric)
            await uow.commit()
        return WorkbookIngestResult(
            template=parsed.template,
            upserted=len(parsed.rows),
            duplicates=parsed.duplicate_count,
            errors=parsed.errors,
        )

    async def sync_thinkingdata(self, stat_date: date) -> ThinkingDataSyncResult:
        configuration = await self._connector.configuration()
        if not configuration.sql_template:
            raise RuleViolation("未配置 td_daily_metrics_sql（系统配置页设置）")
        sql = configuration.sql_template.replace("${stat_date}", stat_date.isoformat())
        rows = await self._connector.query(sql)
        upserts: list[DailyMetricUpsert] = []
        for row in rows:
            product = str(row.get(configuration.mapping["product"]) or "").strip()
            if not product:
                continue
            metric = DailyMetricUpsert(
                stat_date=stat_date,
                product=product,
                source="thinkingdata",
                fields={
                    "dau": row.get(configuration.mapping["dau"]),
                    "new_users": row.get(configuration.mapping["new_users"]),
                },
            )
            metric.validate()
            upserts.append(metric)
        async with self._uow_factory() as uow:
            for metric in upserts:
                await uow.metrics.upsert(metric)
            await uow.commit()
        return ThinkingDataSyncResult(stat_date=stat_date, upserted=len(upserts))

    async def test_connector(self, stat_date: date) -> ConnectorReadResult:
        configuration = await self._connector.configuration()
        missing = [
            name
            for name, value in (
                ("TD 地址", configuration.base_url),
                ("TD 密钥", configuration.api_secret),
                ("拉取 SQL", configuration.sql_template),
            )
            if not value
        ]
        if missing:
            return ConnectorReadResult(
                status="not_configured",
                row_count=0,
                sample=(),
                message=f"未配置：{'、'.join(missing)}（系统配置页填写）",
            )
        sql = configuration.sql_template.replace("${stat_date}", stat_date.isoformat())
        try:
            rows = await self._connector.query(sql)
        except ConnectorReadFailure as exc:
            return ConnectorReadResult(
                status="fail",
                row_count=0,
                sample=(),
                message=str(exc)[:200],
            )
        sample = tuple(
            {
                "product": row.get(configuration.mapping["product"]),
                "dau": row.get(configuration.mapping["dau"]),
                "new_users": row.get(configuration.mapping["new_users"]),
            }
            for row in rows[:3]
        )
        message = (
            f"读到 {len(rows)} 行"
            if rows
            else "查询成功但返回 0 行（检查 SQL 与统计日）"
        )
        return ConnectorReadResult(
            status="ok",
            row_count=len(rows),
            sample=sample,
            message=message,
        )

    async def list_daily(self, stat_date: date) -> tuple[DailyMetricSnapshot, ...]:
        async with self._uow_factory() as uow:
            return await uow.metrics.list_for_date(stat_date)

    async def list_events(self, stat_date: date) -> tuple[EventViewSnapshot, ...]:
        configuration = await self._connector.configuration()
        if not configuration.base_url or not configuration.api_secret:
            return tuple(
                EventViewSnapshot(
                    view=view,
                    product=product,
                    events=(),
                    error="未配置 TD 地址/密钥",
                )
                for view, product in configuration.event_views
            )
        result: list[EventViewSnapshot] = []
        for view, product in configuration.event_views:
            sql = (
                f'select "$part_event" as ev, count(*) as cnt '
                f'from {view} where "$part_date" = \'{stat_date.isoformat()}\' '
                f'group by "$part_event" order by cnt desc'
            )
            try:
                rows = await self._connector.query(sql)
                async with self._uow_factory() as uow:
                    aliases = await uow.aliases.aliases_for(view)
                events = tuple(
                    EventMetric(
                        event_code=str(row.get("ev") or ""),
                        count=_event_count(row.get("cnt") or 0),
                        display_name=aliases.get(str(row.get("ev") or ""), ""),
                    )
                    for row in rows
                    if row.get("ev")
                )
                result.append(
                    EventViewSnapshot(view=view, product=product, events=events)
                )
            except Exception as exc:  # noqa: BLE001 - isolate one view from the others
                result.append(
                    EventViewSnapshot(
                        view=view,
                        product=product,
                        events=(),
                        error=str(exc)[:200],
                    )
                )
        return tuple(result)

    async def save_event_aliases(
        self, updates: tuple[EventAliasUpdate, ...]
    ) -> int:
        async with self._uow_factory() as uow:
            saved = await uow.aliases.save(updates)
            await uow.commit()
        return saved
