"""Connector Management persistence and collaboration ports."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from types import TracebackType
from typing import Protocol, Self

from app.contexts.foundations.integration.connector_management.domain.models import Connector


class ConnectorRepository(Protocol):
    async def get(self, connector_id: uuid.UUID) -> Connector | None: ...

    async def code_exists(self, code: str) -> bool: ...

    async def list_records(self) -> Sequence[Connector]: ...

    async def add(self, connector: Connector) -> None: ...

    async def save(self, connector: Connector) -> None: ...

    async def soft_delete(self, connector_id: uuid.UUID) -> None: ...


class ExpertDirectoryPort(Protocol):
    async def exists(self, expert_id: uuid.UUID) -> bool: ...

    async def names(self, expert_ids: tuple[uuid.UUID, ...]) -> dict[uuid.UUID, str]: ...


class SecretStatusPort(Protocol):
    def status(self, secret_ref: str | None) -> str: ...


class ConnectorChangePublisher(Protocol):
    async def publish(self, connector: Connector) -> None: ...


class ConnectorUnitOfWork(Protocol):
    connectors: ConnectorRepository
    changes: ConnectorChangePublisher

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...
