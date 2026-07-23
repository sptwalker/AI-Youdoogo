"""Published Connector Management queries for other Context adapters."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.integration.connector_management.contracts import (
    ConnectorSnapshot,
)
from app.contexts.foundations.integration.connector_management.entrypoints.operations import (
    list_connectors,
)


async def connector_catalog(
    session: AsyncSession,
) -> tuple[ConnectorSnapshot, ...]:
    """Return immutable connector snapshots; callers cannot mutate source facts."""
    return await list_connectors(session)
