"""Audit Trail-owned persistence and failure-reporting ports."""

from __future__ import annotations

import uuid
from typing import Protocol

from app.contexts.foundations.governance.audit_trail.contracts.audit import (
    AppendAuditRecordCommand,
    AuditRecordView,
    AuditTrailQuery,
)


class AuditRecordRepositoryPort(Protocol):
    async def add(self, command: AppendAuditRecordCommand) -> None: ...

    async def list(self, query: AuditTrailQuery) -> tuple[AuditRecordView, ...]: ...

    async def count(self, query: AuditTrailQuery) -> int: ...


class AuditUnitOfWork(Protocol):
    records: AuditRecordRepositoryPort

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


class AuditUnitOfWorkFactory(Protocol):
    def __call__(self) -> AuditUnitOfWork: ...


class AuditFailureReporterPort(Protocol):
    def record_failure(self, action: str, actor_id: uuid.UUID | None) -> None: ...
