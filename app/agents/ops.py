"""One-way compatibility facade for operational Agent analysis."""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.business.operational_analytics.entrypoints.agent_operations import (
    OPS_DIRECTOR_CODE,
    MetricAlert,
    create_anomaly_alert,
    create_daily_report,
    create_operational_proposal,
)
from app.contexts.business.operational_analytics.entrypoints.agent_operations import (
    format_metrics as _format_metrics,
)
from app.contexts.foundations.execution.agent_execution.contracts.records import (
    AgentExecutionRecordView,
)


def format_metrics(rows: Sequence[Mapping[str, object]]) -> str:
    return _format_metrics(rows)


async def generate_daily_report(
    db: AsyncSession,
    *,
    stat_date: str,
    rows: Sequence[Mapping[str, object]],
    operator_id: uuid.UUID | None = None,
) -> AgentExecutionRecordView:
    return await create_daily_report(
        db,
        stat_date=stat_date,
        rows=rows,
        operator_id=operator_id,
        notify=False,
    )


async def generate_anomaly_alert(
    db: AsyncSession,
    *,
    stat_date: str,
    alerts: Sequence[MetricAlert],
    operator_id: uuid.UUID | None = None,
) -> AgentExecutionRecordView:
    return await create_anomaly_alert(
        db,
        stat_date=stat_date,
        alerts=alerts,
        operator_id=operator_id,
        notify=False,
    )


async def generate_proposal(
    db: AsyncSession,
    *,
    topic: str,
    context: str = "",
    operator_id: uuid.UUID | None = None,
) -> AgentExecutionRecordView:
    return await create_operational_proposal(
        db,
        topic=topic,
        context=context,
        operator_id=operator_id,
    )


Alert = MetricAlert

__all__ = [
    "Alert",
    "OPS_DIRECTOR_CODE",
    "format_metrics",
    "generate_anomaly_alert",
    "generate_daily_report",
    "generate_proposal",
]
