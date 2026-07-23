"""Request-scoped Connector Management operations."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.integration.connector_management.application.contracts import (
    RegisterConnector,
    UpdateConnector,
)
from app.contexts.foundations.integration.connector_management.contracts import ConnectorSnapshot
from app.contexts.foundations.integration.connector_management.infrastructure.composition import (
    build_connector_management,
)


async def list_connectors(session: AsyncSession) -> tuple[ConnectorSnapshot, ...]:
    return await build_connector_management(session).list()


async def get_connector(
    session: AsyncSession, connector_id: uuid.UUID
) -> ConnectorSnapshot:
    return await build_connector_management(session).get(connector_id)


async def register_connector(
    session: AsyncSession, command: RegisterConnector
) -> ConnectorSnapshot:
    return await build_connector_management(session).register(command)


async def update_connector(
    session: AsyncSession, command: UpdateConnector
) -> ConnectorSnapshot:
    return await build_connector_management(session).update(command)


async def delete_connector(session: AsyncSession, connector_id: uuid.UUID) -> None:
    await build_connector_management(session).delete(connector_id)
