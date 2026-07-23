"""Request-scoped published operations for Audit Trail callers."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.governance.audit_trail.contracts.audit import (
    AppendAuditRecordCommand,
    AuditRecordView,
    AuditTrailQuery,
)
from app.contexts.foundations.governance.audit_trail.infrastructure.composition import (
    build_audit_trail,
)


async def append_audit_record(
    session: AsyncSession,
    command: AppendAuditRecordCommand,
) -> None:
    """Append redacted, best-effort audit evidence."""
    await build_audit_trail(session).append(command)


async def query_audit_trail(
    session: AsyncSession,
    query: AuditTrailQuery,
) -> tuple[AuditRecordView, ...]:
    """Query immutable audit evidence in reverse chronological order."""
    return await build_audit_trail(session).query(query)
