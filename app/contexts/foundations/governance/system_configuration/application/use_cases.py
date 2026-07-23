"""Resolve and update configuration while retaining sole write ownership."""

from __future__ import annotations

from app.contexts.foundations.governance.system_configuration.application.ports import (
    ConfigurationAuditPort,
    ConfigurationUnitOfWork,
    RuntimeConfigurationPort,
)
from app.contexts.foundations.governance.system_configuration.contracts.configuration import (
    ConfigView,
    UpdateConfigCommand,
)
from app.contexts.shared_kernel import ResourceNotFound, RuleViolation


class ResolveConfiguration:
    def __init__(self, unit: ConfigurationUnitOfWork) -> None:
        self._unit = unit

    async def execute(self, key: str, default: object = None) -> object:
        config = await self._unit.configurations.get(key)
        return config.value if config is not None else default


class ListConfigurations:
    def __init__(self, unit: ConfigurationUnitOfWork) -> None:
        self._unit = unit

    async def execute(self) -> tuple[ConfigView, ...]:
        return await self._unit.configurations.list()


class UpdateConfiguration:
    def __init__(
        self,
        unit: ConfigurationUnitOfWork,
        runtime: RuntimeConfigurationPort,
        audit: ConfigurationAuditPort,
    ) -> None:
        self._unit = unit
        self._runtime = runtime
        self._audit = audit

    async def execute(self, command: UpdateConfigCommand) -> ConfigView:
        current = await self._unit.configurations.get(command.key)
        if current is None:
            raise ResourceNotFound("配置项不存在")
        if not current.is_editable:
            raise RuleViolation("该配置项不可编辑")
        updated = await self._unit.configurations.update(
            command.key, command.value, command.updated_by
        )
        await self._unit.commit()
        self._runtime.set_override(command.key, command.value)
        await self._audit.record_update(
            config_id=updated.config_id,
            key=command.key,
            actor_id=command.updated_by,
            actor_role=command.actor_role,
        )
        return updated
