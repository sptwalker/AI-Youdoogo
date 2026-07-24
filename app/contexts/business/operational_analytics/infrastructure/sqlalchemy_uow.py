"""Operational Analytics Unit of Work."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.business.operational_analytics.application.ports import (
    DailyMetricRepository,
    EventAliasRepository,
)
from app.contexts.business.operational_analytics.infrastructure.sqlalchemy_event_repository import (
    SQLAlchemyEventAliasRepository,
)
from app.contexts.business.operational_analytics.infrastructure.sqlalchemy_repository import (
    SQLAlchemyDailyMetricRepository,
)
from app.platform.database.unit_of_work import SessionUnitOfWork


class SQLAlchemyOperationalAnalyticsUnitOfWork(SessionUnitOfWork):
    metrics: DailyMetricRepository
    aliases: EventAliasRepository

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self.metrics = SQLAlchemyDailyMetricRepository(session)
        self.aliases = SQLAlchemyEventAliasRepository(session)

    def _prepare_for_use(self) -> None:
        self.metrics = SQLAlchemyDailyMetricRepository(self._session)
        self.aliases = SQLAlchemyEventAliasRepository(self._session)
