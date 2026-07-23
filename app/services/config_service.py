"""One-way compatibility facade for the System Configuration context."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.governance.system_configuration.contracts.configuration import (
    UpdateConfigCommand,
)
from app.contexts.foundations.governance.system_configuration.infrastructure import (
    sqlalchemy_adapter,
)
from app.models.sys_config import SysConfig
from app.services import audit_service


def _operations(db: AsyncSession) -> sqlalchemy_adapter.SQLAlchemySystemConfiguration:
    return sqlalchemy_adapter.SQLAlchemySystemConfiguration(
        db, audit_callback=audit_service.audit
    )


async def _get(db: AsyncSession, key: str) -> SysConfig | None:
    return await _operations(db).get_record(key)


async def resolve(db: AsyncSession, key: str, default: Any = None) -> Any:
    return await _operations(db).resolve(key, default)


async def all_values(db: AsyncSession) -> dict[str, Any]:
    return await _operations(db).all_values()


def _is_set(value: Any) -> bool:
    return value is not None and value != ""


async def list_configs(db: AsyncSession) -> list[dict[str, Any]]:
    return await _operations(db).list_configs()


async def set_config(
    db: AsyncSession,
    key: str,
    value: Any,
    *,
    updated_by: uuid.UUID | None,
    actor_role: str | None,
) -> SysConfig:
    return await _operations(db).update(
        UpdateConfigCommand(
            key=key,
            value=value,
            updated_by=updated_by,
            actor_role=actor_role,
        )
    )
