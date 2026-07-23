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


class SQLAlchemyOperationalAnalyticsUnitOfWork:
    metrics: DailyMetricRepository
    aliases: EventAliasRepository

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self.metrics = SQLAlchemyDailyMetricRepository(session)
        self.aliases = SQLAlchemyEventAliasRepository(session)

    async def __aenter__(self) -> SQLAlchemyOperationalAnalyticsUnitOfWork:
        self.metrics = SQLAlchemyDailyMetricRepository(self._session)
        self.aliases = SQLAlchemyEventAliasRepository(self._session)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object | None,
    ) -> None:
        if exc_type is not None:
            await self.rollback()

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()
