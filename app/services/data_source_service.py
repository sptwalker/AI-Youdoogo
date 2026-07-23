"""Compatibility facade for Connector Management."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.integration.connector_management.application.contracts import (
    RegisterConnector,
    UpdateConnector,
)
from app.contexts.foundations.integration.connector_management.contracts import ConnectorSnapshot
from app.contexts.foundations.integration.connector_management.domain.models import (
    VALID_CONNECTOR_TYPES,
)
from app.contexts.foundations.integration.connector_management.entrypoints import operations
from app.contexts.foundations.integration.connector_management.infrastructure.adapters import (
    EnvironmentSecretStatusAdapter,
)

VALID_TYPES = VALID_CONNECTOR_TYPES


async def get_ds(db: AsyncSession, ds_id: uuid.UUID) -> ConnectorSnapshot:
    return await operations.get_connector(db, ds_id)


async def create_ds(
    db: AsyncSession,
    *,
    name: str,
    type: str,
    code: str | None = None,
    department_id: uuid.UUID | None = None,
    config: dict[str, Any] | None = None,
    secret_ref: str | None = None,
    owner_agent_id: uuid.UUID | None = None,
) -> ConnectorSnapshot:
    return await operations.register_connector(
        db,
        RegisterConnector(
            name=name,
            connector_type=type,
            code=code,
            department_id=department_id,
            config=config,
            secret_ref=secret_ref,
            owner_expert_id=owner_agent_id,
        ),
    )


async def update_ds(
    db: AsyncSession,
    ds_id: uuid.UUID,
    *,
    name: str | None = None,
    config: dict[str, Any] | None = None,
    secret_ref: str | None = None,
    is_active: bool | None = None,
    department_id: uuid.UUID | None = None,
    owner_agent_id: uuid.UUID | None = None,
) -> ConnectorSnapshot:
    return await operations.update_connector(
        db,
        UpdateConnector(
            connector_id=ds_id,
            name=name,
            config=config,
            secret_ref=secret_ref,
            is_active=is_active,
            department_id=department_id,
            owner_expert_id=owner_agent_id,
        ),
    )


async def delete_ds(db: AsyncSession, ds_id: uuid.UUID) -> None:
    await operations.delete_connector(db, ds_id)


def _secret_status(secret_ref: str | None) -> str:
    return EnvironmentSecretStatusAdapter().status(secret_ref)


async def list_ds(db: AsyncSession) -> list[dict[str, Any]]:
    return [snapshot.to_dict() for snapshot in await operations.list_connectors(db)]
