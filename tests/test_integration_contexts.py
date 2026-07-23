"""Fake-based application tests for Connector, Query, and Analytics boundaries."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Self

import pytest

from app.contexts.business.operational_analytics.application.contracts import (
    AnalyticsConnectorConfiguration,
    ParsedMetricRow,
    ParsedWorkbook,
)
from app.contexts.business.operational_analytics.application.mapping import DEFAULT_MAPPING
from app.contexts.business.operational_analytics.application.use_cases import (
    OperationalAnalytics,
)
from app.contexts.business.operational_analytics.contracts import DailyMetricSnapshot
from app.contexts.business.operational_analytics.domain.models import DailyMetricUpsert
from app.contexts.foundations.integration.connector_management.application.contracts import (
    RegisterConnector,
)
from app.contexts.foundations.integration.connector_management.application.use_cases import (
    ConnectorManagement,
)
from app.contexts.foundations.integration.connector_management.domain.models import Connector
from app.contexts.foundations.integration.governed_data_query.application.contracts import (
    ConnectorQueryConfiguration,
    QueryAuditEvidence,
)
from app.contexts.foundations.integration.governed_data_query.application.use_cases import (
    GovernedDataQuery,
)
from app.contexts.foundations.integration.governed_data_query.contracts import (
    CatalogView,
    DataCatalogSnapshot,
    GovernedQueryRequest,
)
from app.contexts.shared_kernel import ResourceNotFound, RuleViolation


class _ConnectorRepository:
    def __init__(self) -> None:
        self.records: dict[uuid.UUID, Connector] = {}

    async def get(self, connector_id: uuid.UUID) -> Connector | None:
        return self.records.get(connector_id)

    async def code_exists(self, code: str) -> bool:
        return any(record.code == code for record in self.records.values())

    async def list_records(self) -> tuple[Connector, ...]:
        return tuple(self.records.values())

    async def add(self, connector: Connector) -> None:
        self.records[connector.id] = connector

    async def save(self, connector: Connector) -> None:
        self.records[connector.id] = connector

    async def soft_delete(self, connector_id: uuid.UUID) -> None:
        self.records.pop(connector_id, None)


class _ConnectorChanges:
    def __init__(self) -> None:
        self.ids: list[uuid.UUID] = []

    async def publish(self, connector: Connector) -> None:
        self.ids.append(connector.id)


class _ConnectorUow:
    def __init__(self) -> None:
        self.connectors = _ConnectorRepository()
        self.changes = _ConnectorChanges()
        self.commits = 0

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        return None


class _Experts:
    def __init__(self, names: dict[uuid.UUID, str]) -> None:
        self._names = names

    async def exists(self, expert_id: uuid.UUID) -> bool:
        return expert_id in self._names

    async def names(self, expert_ids: tuple[uuid.UUID, ...]) -> dict[uuid.UUID, str]:
        return {expert_id: self._names[expert_id] for expert_id in expert_ids}


class _Secrets:
    def status(self, secret_ref: str | None) -> str:
        return "configured" if secret_ref else "not_set"


async def test_connector_use_case_owns_validation_event_and_commit() -> None:
    expert_id = uuid.uuid4()
    uow = _ConnectorUow()
    application = ConnectorManagement(
        lambda: uow,
        experts=_Experts({expert_id: "数据专家"}),
        secrets=_Secrets(),
    )
    snapshot = await application.register(
        RegisterConnector(
            name="TD",
            connector_type="thinkingdata",
            owner_expert_id=expert_id,
            secret_ref="TD_API_SECRET",
        )
    )
    assert snapshot.owner_expert_id == expert_id
    assert snapshot.secret_status == "configured"
    assert uow.changes.ids == [snapshot.id]
    assert uow.commits == 1

    with pytest.raises(ResourceNotFound, match="对接AI不存在"):
        await application.register(
            RegisterConnector(
                name="missing",
                connector_type="http_api",
                owner_expert_id=uuid.uuid4(),
            )
        )
    with pytest.raises(RuleViolation, match="type"):
        await application.register(
            RegisterConnector(name="bad", connector_type="database")
        )


class _Catalog:
    async def snapshot(self) -> DataCatalogSnapshot:
        return DataCatalogSnapshot(
            sources=(),
            views=(CatalogView(view="v_event_4", product="盒子"),),
        )


class _QueryConnector:
    def __init__(self) -> None:
        self.calls = 0

    async def configuration(self) -> ConnectorQueryConfiguration:
        return ConnectorQueryConfiguration(base_url="http://td", api_secret="secret")

    async def execute(
        self, configuration: ConnectorQueryConfiguration, sql: str, *, timeout: int
    ) -> list[dict[str, object]]:
        del configuration, sql, timeout
        self.calls += 1
        return [
            {"event": "a", "count": 1, "extra": "x"},
            {"event": "b", "count": 2, "extra": "y"},
            {"event": "c", "count": 3, "extra": "z"},
        ]


class _Audit:
    def __init__(self) -> None:
        self.records: list[QueryAuditEvidence] = []

    async def record(self, evidence: QueryAuditEvidence) -> None:
        self.records.append(evidence)


async def test_governed_query_rejects_before_io_and_caps_results() -> None:
    connector = _QueryConnector()
    audit = _Audit()
    application = GovernedDataQuery(
        catalog=_Catalog(),
        connector=connector,
        audit=audit,
        max_rows=2,
        max_columns=2,
    )
    rejected = await application.run(
        GovernedQueryRequest(sql="drop table x", actor_id=None, actor_role=None)
    )
    assert rejected.status == "rejected"
    assert connector.calls == 0
    assert audit.records[-1].result == "rejected"

    result = await application.run(
        GovernedQueryRequest(
            sql="select * from v_event_4",
            actor_id=uuid.uuid4(),
            actor_role="admin",
        )
    )
    assert result.row_count == 2
    assert result.columns == ("event", "count")
    assert result.truncated
    assert connector.calls == 1
    assert audit.records[-1].result == "ok"


class _MetricRepository:
    def __init__(self) -> None:
        self.upserts: list[DailyMetricUpsert] = []

    async def upsert(self, metric: DailyMetricUpsert) -> None:
        self.upserts.append(metric)

    async def list_for_date(self, stat_date: date) -> tuple[DailyMetricSnapshot, ...]:
        del stat_date
        return ()


class _AnalyticsUow:
    def __init__(self) -> None:
        self.metrics = _MetricRepository()
        self.commits = 0

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        return None


class _Parser:
    def parse(self, content: bytes) -> ParsedWorkbook:
        assert content == b"xlsx"
        return ParsedWorkbook(
            template="ops_daily/v1",
            rows=(
                ParsedMetricRow(
                    stat_date=date(2026, 7, 23),
                    product="产品A",
                    dau=10,
                    new_users=2,
                    retention_d1=30.0,
                ),
            ),
            errors=(),
            duplicate_count=0,
        )


class _AnalyticsConnector:
    async def configuration(self) -> AnalyticsConnectorConfiguration:
        return AnalyticsConnectorConfiguration(
            base_url="http://td",
            api_secret="secret",
            sql_template="select '${stat_date}'",
            mapping=dict(DEFAULT_MAPPING),
            event_views=(("v_event_4", "盒子"),),
        )

    async def query(self, sql: str) -> list[dict[str, object]]:
        assert "2026-07-23" in sql
        return [{"product": "产品B", "dau": 20, "new_users": 3}]


async def test_operational_analytics_application_owns_ingest_transactions() -> None:
    uow = _AnalyticsUow()
    application = OperationalAnalytics(
        lambda: uow,
        parser=_Parser(),
        connector=_AnalyticsConnector(),
    )
    workbook = await application.ingest_workbook(b"xlsx")
    assert workbook.upserted == 1
    assert uow.metrics.upserts[-1].source == "excel"
    assert uow.commits == 1

    synced = await application.sync_thinkingdata(date(2026, 7, 23))
    assert synced.upserted == 1
    assert uow.metrics.upserts[-1].source == "thinkingdata"
    assert uow.commits == 2
