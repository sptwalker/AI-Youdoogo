"""System Configuration-owned ports and transaction boundary."""

from __future__ import annotations

import uuid
from typing import Protocol

from app.contexts.foundations.governance.system_configuration.contracts.configuration import (
    ConfigView,
)


class ConfigurationRepositoryPort(Protocol):
    async def get(self, key: str) -> ConfigView | None: ...

    async def list(self) -> tuple[ConfigView, ...]: ...

    async def update(
        self, key: str, value: object, updated_by: uuid.UUID | None
    ) -> ConfigView: ...


class ConfigurationUnitOfWork(Protocol):
    configurations: ConfigurationRepositoryPort

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


class RuntimeConfigurationPort(Protocol):
    def set_override(self, key: str, value: object) -> None: ...


class ConfigurationAuditPort(Protocol):
    async def record_update(
        self,
        *,
        config_id: uuid.UUID,
        key: str,
        actor_id: uuid.UUID | None,
        actor_role: str | None,
    ) -> None: ...
