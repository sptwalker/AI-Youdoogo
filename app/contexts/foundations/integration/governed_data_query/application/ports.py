"""Ports owned by Governed Data Query application policy."""

from __future__ import annotations

from typing import Protocol

from app.contexts.foundations.integration.governed_data_query.application.contracts import (
    ConnectorQueryConfiguration,
    QueryAuditEvidence,
)
from app.contexts.foundations.integration.governed_data_query.contracts import (
    DataCatalogSnapshot,
)


class ConnectorExecutionFailure(Exception):
    """Normalized failure from a governed connector query."""


class DataCatalogPort(Protocol):
    async def snapshot(self) -> DataCatalogSnapshot: ...


class ConnectorExecutionPort(Protocol):
    async def configuration(self) -> ConnectorQueryConfiguration: ...

    async def execute(
        self, configuration: ConnectorQueryConfiguration, sql: str, *, timeout: int
    ) -> list[dict[str, object]]: ...


class AuditEvidencePort(Protocol):
    async def record(self, evidence: QueryAuditEvidence) -> None: ...
