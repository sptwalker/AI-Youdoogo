"""Append and query immutable audit evidence."""

from __future__ import annotations

from dataclasses import replace

from app.contexts.foundations.governance.audit_trail.application.ports import (
    AuditFailureReporterPort,
    AuditUnitOfWorkFactory,
)
from app.contexts.foundations.governance.audit_trail.contracts.audit import (
    AppendAuditRecordCommand,
    AuditRecordView,
    AuditTrailPage,
    AuditTrailQuery,
)
from app.contexts.foundations.governance.audit_trail.domain.redaction import mask_secrets


class AppendAuditRecord:
    def __init__(
        self,
        units: AuditUnitOfWorkFactory,
        failures: AuditFailureReporterPort,
    ) -> None:
        self._units = units
        self._failures = failures

    async def execute(self, command: AppendAuditRecordCommand) -> None:
        safe_command = replace(command, detail=mask_secrets(command.detail))
        for attempt in (1, 2):
            unit = self._units()
            try:
                await unit.records.add(safe_command)
                await unit.commit()
                return
            except Exception:  # noqa: BLE001 - audit evidence must not block source work
                await unit.rollback()
                if attempt == 2:
                    self._failures.record_failure(command.action, command.actor_id)


class QueryAuditTrail:
    def __init__(self, units: AuditUnitOfWorkFactory) -> None:
        self._units = units

    async def execute(self, query: AuditTrailQuery) -> tuple[AuditRecordView, ...]:
        return await self._units().records.list(query)

    async def execute_page(self, query: AuditTrailQuery) -> AuditTrailPage:
        """一次取当前页 + 满足筛选的总数（服务端翻页）。"""
        records = self._units().records
        return AuditTrailPage(
            items=await records.list(query),
            total=await records.count(query),
        )
