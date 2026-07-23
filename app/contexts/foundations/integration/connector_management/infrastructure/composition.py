"""Request-scoped Connector Management composition."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.integration.connector_management.application.use_cases import (
    ConnectorManagement,
)
from app.contexts.foundations.integration.connector_management.infrastructure import (
    sqlalchemy_uow,
)
from app.contexts.foundations.integration.connector_management.infrastructure.adapters import (
    EnvironmentSecretStatusAdapter,
    ExpertRosterAdapter,
)


def build_connector_management(session: AsyncSession) -> ConnectorManagement:
    return ConnectorManagement(
        uow_factory=lambda: sqlalchemy_uow.SQLAlchemyConnectorUnitOfWork(session),
        experts=ExpertRosterAdapter(session),
        secrets=EnvironmentSecretStatusAdapter(),
    )
