"""Request-scoped operations for operational reports and anomaly analysis."""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.business.operational_analytics.agent_contracts import (
    AnomalyAlertCommand,
    AnomalyCheckCommand,
    AnomalyCheckResult,
    DailyReportCommand,
    MetricAlert,
    MetricRowInput,
    OperationalProposalCommand,
)
from app.contexts.business.operational_analytics.application.agent_use_cases import (
    OPS_DIRECTOR_CODE,
)
from app.contexts.business.operational_analytics.application.agent_use_cases import (
    format_metrics as format_metric_inputs,
)
from app.contexts.business.operational_analytics.domain.anomaly import (
    detect_metric_anomalies,
)
from app.contexts.business.operational_analytics.infrastructure.agent_composition import (
    build_operational_agent_analytics,
)
from app.contexts.foundations.execution.agent_execution.contracts.records import (
    AgentExecutionRecordView,
)


def metric_rows(rows: Sequence[Mapping[str, object]]) -> tuple[MetricRowInput, ...]:
    return tuple(
        MetricRowInput(
            stat_date=_optional_str(row.get("stat_date")),
            product=_optional_str(row.get("product")),
            dau=_optional_int(row.get("dau")),
            new_users=_optional_int(row.get("new_users")),
            retention_d1=_optional_float(row.get("retention_d1")),
        )
        for row in rows
    )


def detect_anomalies(
    today: Sequence[Mapping[str, object]],
    prev: Sequence[Mapping[str, object]],
    *,
    dau_drop_pct: float = 0.2,
    new_drop_pct: float = 0.3,
    retention_floor: float = 30.0,
) -> list[MetricAlert]:
    return list(
        detect_metric_anomalies(
            metric_rows(today),
            metric_rows(prev),
            dau_drop_pct=dau_drop_pct,
            new_drop_pct=new_drop_pct,
            retention_floor=retention_floor,
        )
    )


def format_metrics(rows: Sequence[Mapping[str, object]]) -> str:
    return format_metric_inputs(metric_rows(rows))


async def create_daily_report(
    session: AsyncSession,
    *,
    stat_date: str,
    rows: Sequence[Mapping[str, object]] | None,
    operator_id: uuid.UUID | None,
    notify: bool = True,
) -> AgentExecutionRecordView:
    inputs = metric_rows(rows) if rows is not None else None
    return await build_operational_agent_analytics(
        session, notifications_enabled=notify
    ).daily_report(DailyReportCommand(stat_date, inputs, operator_id))


async def check_anomalies(
    session: AsyncSession,
    *,
    stat_date: str,
    operator_id: uuid.UUID | None,
    notify: bool = True,
) -> AnomalyCheckResult:
    return await build_operational_agent_analytics(
        session, notifications_enabled=notify
    ).anomaly_check(AnomalyCheckCommand(stat_date, operator_id))


async def create_anomaly_alert(
    session: AsyncSession,
    *,
    stat_date: str,
    alerts: Sequence[MetricAlert],
    operator_id: uuid.UUID | None,
    notify: bool = False,
) -> AgentExecutionRecordView:
    return await build_operational_agent_analytics(
        session, notifications_enabled=notify
    ).anomaly_alert(AnomalyAlertCommand(stat_date, tuple(alerts), operator_id))


async def create_operational_proposal(
    session: AsyncSession,
    *,
    topic: str,
    context: str,
    operator_id: uuid.UUID | None,
) -> AgentExecutionRecordView:
    return await build_operational_agent_analytics(
        session, notifications_enabled=False
    ).proposal(OperationalProposalCommand(topic, context, operator_id))


def _optional_str(value: object) -> str | None:
    return None if value is None else str(value)


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    return int(value) if isinstance(value, (int, float, str)) else None


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    return float(value) if isinstance(value, (int, float, str)) else None


__all__ = [
    "OPS_DIRECTOR_CODE",
    "MetricAlert",
    "check_anomalies",
    "create_anomaly_alert",
    "create_daily_report",
    "create_operational_proposal",
    "detect_anomalies",
    "format_metrics",
]
