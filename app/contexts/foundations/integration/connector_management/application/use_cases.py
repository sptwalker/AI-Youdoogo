"""Connector Management application service."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from app.contexts.foundations.integration.connector_management.application.contracts import (
    RegisterConnector,
    UpdateConnector,
)
from app.contexts.foundations.integration.connector_management.application.ports import (
    ConnectorUnitOfWork,
    ExpertDirectoryPort,
    SecretStatusPort,
)
from app.contexts.foundations.integration.connector_management.contracts import ConnectorSnapshot
from app.contexts.foundations.integration.connector_management.domain.models import Connector
from app.contexts.shared_kernel import ConflictDetected, ResourceNotFound

UowFactory = Callable[[], ConnectorUnitOfWork]


class ConnectorManagement:
    def __init__(
        self,
        uow_factory: UowFactory,
        *,
        experts: ExpertDirectoryPort,
        secrets: SecretStatusPort,
    ) -> None:
        self._uow_factory = uow_factory
        self._experts = experts
        self._secrets = secrets

    def _snapshot(
        self, connector: Connector, *, owner_name: str | None = None
    ) -> ConnectorSnapshot:
        return ConnectorSnapshot(
            id=connector.id,
            name=connector.name,
            code=connector.code,
            connector_type=connector.connector_type,
            department_id=connector.department_id,
            config=dict(connector.config),
            secret_ref=connector.secret_ref,
            secret_status=self._secrets.status(connector.secret_ref),
            is_active=connector.is_active,
            owner_expert_id=connector.owner_expert_id,
            owner_expert_name=owner_name,
        )

    async def list(self) -> tuple[ConnectorSnapshot, ...]:
        async with self._uow_factory() as uow:
            records = await uow.connectors.list_records()
        owner_ids = tuple(
            connector.owner_expert_id
            for connector in records
            if connector.owner_expert_id is not None
        )
        names = await self._experts.names(owner_ids)
        return tuple(
            self._snapshot(
                connector,
                owner_name=names.get(connector.owner_expert_id)
                if connector.owner_expert_id
                else None,
            )
            for connector in records
        )

    async def get(self, connector_id: uuid.UUID) -> ConnectorSnapshot:
        async with self._uow_factory() as uow:
            connector = await uow.connectors.get(connector_id)
        if connector is None:
            raise ResourceNotFound("数据接口不存在")
        owner_name = None
        if connector.owner_expert_id:
            owner_name = (await self._experts.names((connector.owner_expert_id,))).get(
                connector.owner_expert_id
            )
        return self._snapshot(connector, owner_name=owner_name)

    async def register(self, command: RegisterConnector) -> ConnectorSnapshot:
        connector = Connector(
            id=uuid.uuid4(),
            name=command.name,
            code=command.code or f"ds_{uuid.uuid4().hex[:8]}",
            connector_type=command.connector_type,
            department_id=command.department_id,
            config=dict(command.config or {}),
            secret_ref=command.secret_ref,
            owner_expert_id=command.owner_expert_id,
        )
        connector.validate()
        if connector.owner_expert_id and not await self._experts.exists(
            connector.owner_expert_id
        ):
            raise ResourceNotFound("指定的对接AI不存在")
        async with self._uow_factory() as uow:
            if await uow.connectors.code_exists(connector.code):
                raise ConflictDetected("数据接口编码已存在")
            await uow.connectors.add(connector)
            await uow.changes.publish(connector)
            await uow.commit()
        return self._snapshot(connector)

    async def update(self, command: UpdateConnector) -> ConnectorSnapshot:
        async with self._uow_factory() as uow:
            connector = await uow.connectors.get(command.connector_id)
            if connector is None:
                raise ResourceNotFound("数据接口不存在")
            if command.owner_expert_id and not await self._experts.exists(
                command.owner_expert_id
            ):
                raise ResourceNotFound("指定的对接AI不存在")
            for field in (
                "name",
                "config",
                "secret_ref",
                "is_active",
                "department_id",
                "owner_expert_id",
            ):
                value = getattr(command, field)
                if value is not None:
                    setattr(connector, field, dict(value) if field == "config" else value)
            connector.validate()
            await uow.connectors.save(connector)
            await uow.changes.publish(connector)
            await uow.commit()
        owner_name = None
        if connector.owner_expert_id:
            owner_name = (await self._experts.names((connector.owner_expert_id,))).get(
                connector.owner_expert_id
            )
        return self._snapshot(connector, owner_name=owner_name)

    async def delete(self, connector_id: uuid.UUID) -> None:
        async with self._uow_factory() as uow:
            connector = await uow.connectors.get(connector_id)
            if connector is None:
                raise ResourceNotFound("数据接口不存在")
            await uow.connectors.soft_delete(connector_id)
            await uow.changes.publish(connector)
            await uow.commit()
