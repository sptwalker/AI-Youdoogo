"""SQLAlchemy repository for the existing ops_daily_metric table."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.business.operational_analytics.contracts import DailyMetricSnapshot
from app.contexts.business.operational_analytics.domain.models import DailyMetricUpsert
from app.models.ops_data import OpsDailyMetric

FIELDS = ("dau", "new_users", "retention_d1")


class SQLAlchemyDailyMetricRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(self, metric: DailyMetricUpsert) -> None:
        statement = select(OpsDailyMetric).where(
            OpsDailyMetric.stat_date == metric.stat_date,
            OpsDailyMetric.product == metric.product,
        )
        row = (await self._session.execute(statement)).scalar_one_or_none()
        if row is None:
            self._session.add(
                OpsDailyMetric(
                    stat_date=metric.stat_date,
                    product=metric.product,
                    source=metric.source,
                    **{field: metric.fields.get(field) for field in FIELDS},
                )
            )
        else:
            for field in FIELDS:
                if field in metric.fields:
                    setattr(row, field, metric.fields[field])
            row.source = metric.source
        await self._session.flush()

    async def list_for_date(
        self, stat_date: date
    ) -> tuple[DailyMetricSnapshot, ...]:
        statement = (
            select(OpsDailyMetric)
            .where(
                OpsDailyMetric.stat_date == stat_date,
                OpsDailyMetric.is_delete.is_(False),
            )
            .order_by(OpsDailyMetric.product)
        )
        return tuple(
            DailyMetricSnapshot(
                stat_date=row.stat_date,
                product=row.product,
                dau=row.dau,
                new_users=row.new_users,
                retention_d1=row.retention_d1,
                source=row.source,
            )
            for row in (await self._session.execute(statement)).scalars()
        )
