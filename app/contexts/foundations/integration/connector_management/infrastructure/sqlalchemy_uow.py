"""Connector Unit of Work backed by a caller-owned AsyncSession."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.integration.connector_management.application.ports import (
    ConnectorChangePublisher,
    ConnectorRepository,
)
from app.contexts.foundations.integration.connector_management.infrastructure import (
    sqlalchemy_repository,
)
from app.contexts.foundations.integration.connector_management.infrastructure.adapters import (
    SourceChangePublisher,
)


class SQLAlchemyConnectorUnitOfWork:
    connectors: ConnectorRepository
    changes: ConnectorChangePublisher

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self.connectors = sqlalchemy_repository.SQLAlchemyConnectorRepository(session)
        self.changes = SourceChangePublisher(session)

    async def __aenter__(self) -> SQLAlchemyConnectorUnitOfWork:
        self.connectors = sqlalchemy_repository.SQLAlchemyConnectorRepository(self._session)
        self.changes = SourceChangePublisher(self._session)
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
