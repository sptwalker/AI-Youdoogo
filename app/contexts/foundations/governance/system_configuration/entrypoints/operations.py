"""Request-scoped published System Configuration operations."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.governance.system_configuration.contracts.configuration import (
    ConfigView,
    UpdateConfigCommand,
)
from app.contexts.foundations.governance.system_configuration.infrastructure.composition import (
    build_system_configuration,
)


async def resolve_configuration(
    session: AsyncSession,
    key: str,
    default: object = None,
) -> object:
    return await build_system_configuration(session).resolve.execute(key, default)


async def list_configurations(session: AsyncSession) -> tuple[ConfigView, ...]:
    return await build_system_configuration(session).list.execute()


async def update_configuration(
    session: AsyncSession,
    command: UpdateConfigCommand,
) -> ConfigView:
    return await build_system_configuration(session).update.execute(command)
