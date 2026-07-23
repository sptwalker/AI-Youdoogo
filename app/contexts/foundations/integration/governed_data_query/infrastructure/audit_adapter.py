"""Adapters from governed-query evidence to the published Audit Trail boundary."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.governance.audit_trail import public as audit_public
from app.contexts.foundations.integration.governed_data_query.application.contracts import (
    QueryAuditEvidence,
)


class PublishedAuditEvidenceAdapter:
    """Request-scoped adapter that invokes Audit Trail's published operation."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(self, evidence: QueryAuditEvidence) -> None:
        await audit_public.append_audit_record(
            self._session,
            _to_audit_command(evidence),
        )


class DelegatingAuditEvidenceAdapter:
    """Temporary bridge for callers that already provide the published port."""

    def __init__(self, audit: audit_public.AuditEvidencePort) -> None:
        self._audit = audit

    async def record(self, evidence: QueryAuditEvidence) -> None:
        await self._audit.append(_to_audit_command(evidence))


def _to_audit_command(
    evidence: QueryAuditEvidence,
) -> audit_public.AppendAuditRecordCommand:
    return audit_public.AppendAuditRecordCommand(
        actor_id=evidence.actor_id,
        actor_role=evidence.actor_role,
        action="data.query",
        summary=f"取数[{evidence.source}/{evidence.result}]:{evidence.sql[:60]}",
        target_type="data_source",
        detail={
            "sql": evidence.sql[:2000],
            "source": evidence.source,
            **evidence.detail,
        },
        result=evidence.result,
    )
