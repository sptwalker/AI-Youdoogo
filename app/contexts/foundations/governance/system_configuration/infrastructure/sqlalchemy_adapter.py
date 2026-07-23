"""SQLAlchemy adapter and legacy composition for System Configuration."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.governance.system_configuration.application.ports import (
    ConfigurationRepositoryPort,
)
from app.contexts.foundations.governance.system_configuration.application.use_cases import (
    ListConfigurations,
    ResolveConfiguration,
    UpdateConfiguration,
)
from app.contexts.foundations.governance.system_configuration.contracts.configuration import (
    ConfigView,
    UpdateConfigCommand,
)
from app.core import runtime_config
from app.models.sys_config import SysConfig


def _is_set(value: object) -> bool:
    return value is not None and value != ""


def _to_view(record: SysConfig) -> ConfigView:
    return ConfigView(
        config_id=record.id,
        key=record.key,
        value=record.value,
        value_type=record.value_type,
        category=record.category,
        is_editable=record.is_editable,
        is_secret=record.is_secret,
        is_set=_is_set(record.value),
    )


class SQLAlchemyConfigurationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_record(self, key: str) -> SysConfig | None:
        statement = select(SysConfig).where(
            SysConfig.key == key, SysConfig.is_delete.is_(False)
        )
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def get(self, key: str) -> ConfigView | None:
        record = await self.get_record(key)
        return _to_view(record) if record is not None else None

    async def list(self) -> tuple[ConfigView, ...]:
        statement = (
            select(SysConfig)
            .where(SysConfig.is_delete.is_(False))
            .order_by(SysConfig.category, SysConfig.key)
        )
        rows = (await self._session.execute(statement)).scalars()
        return tuple(_to_view(record) for record in rows)

    async def update(
        self, key: str, value: object, updated_by: uuid.UUID | None
    ) -> ConfigView:
        record = await self.get_record(key)
        if record is None:
            raise RuntimeError("configuration disappeared during update")
        record.value = value
        record.updated_by = updated_by
        await self._session.flush()
        return _to_view(record)


class SQLAlchemyConfigurationUnitOfWork:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self.configurations: ConfigurationRepositoryPort = (
            SQLAlchemyConfigurationRepository(session)
        )

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()


class RuntimeConfigurationAdapter:
    def set_override(self, key: str, value: object) -> None:
        runtime_config.set_override(key, value)


AuditCallback = Callable[..., Awaitable[None]]


class CallbackConfigurationAudit:
    def __init__(self, callback: AuditCallback, session: AsyncSession) -> None:
        self._callback = callback
        self._session = session

    async def record_update(
        self,
        *,
        config_id: uuid.UUID,
        key: str,
        actor_id: uuid.UUID | None,
        actor_role: str | None,
    ) -> None:
        await self._callback(
            self._session,
            actor_id=actor_id,
            actor_role=actor_role,
            action="config.update",
            summary=f"修改配置 {key}",
            target_type="sys_config",
            target_id=config_id,
            detail={"key": key},
        )


class SQLAlchemySystemConfiguration:
    def __init__(self, session: AsyncSession, *, audit_callback: AuditCallback) -> None:
        self._session = session
        self._unit = SQLAlchemyConfigurationUnitOfWork(session)
        self._resolve = ResolveConfiguration(self._unit)
        self._list = ListConfigurations(self._unit)
        self._update = UpdateConfiguration(
            self._unit,
            RuntimeConfigurationAdapter(),
            CallbackConfigurationAudit(audit_callback, session),
        )

    async def resolve(self, key: str, default: object = None) -> object:
        return await self._resolve.execute(key, default)

    async def all_values(self) -> dict[str, object]:
        return {view.key: view.value for view in await self._list.execute()}

    async def list_configs(self) -> list[dict[str, object]]:
        return [
            {
                "key": view.key,
                "value": "" if view.is_secret else view.value,
                "value_type": view.value_type,
                "category": view.category,
                "is_editable": view.is_editable,
                "is_secret": view.is_secret,
                "is_set": view.is_set,
            }
            for view in await self._list.execute()
        ]

    async def update(self, command: UpdateConfigCommand) -> SysConfig:
        result = await self._update.execute(command)
        record = await self._session.get(SysConfig, result.config_id)
        if record is None:
            raise RuntimeError("updated configuration is unavailable")
        return record

    async def get_record(self, key: str) -> SysConfig | None:
        return await SQLAlchemyConfigurationRepository(self._session).get_record(key)
