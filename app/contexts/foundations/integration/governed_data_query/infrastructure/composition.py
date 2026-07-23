"""Request-scoped Governed Data Query composition."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.governance.audit_trail import public as audit_public
from app.contexts.foundations.integration.governed_data_query.application.ports import (
    AuditEvidencePort,
)
from app.contexts.foundations.integration.governed_data_query.application.use_cases import (
    GovernedDataQuery,
)
from app.contexts.foundations.integration.governed_data_query.infrastructure import (
    catalog_adapter,
    connector_adapter,
)
from app.contexts.foundations.integration.governed_data_query.infrastructure.audit_adapter import (
    DelegatingAuditEvidenceAdapter,
    PublishedAuditEvidenceAdapter,
)


def build_governed_data_query(
    session: AsyncSession,
    *,
    audit: audit_public.AuditEvidencePort | None = None,
    max_rows: int = 1000,
    max_columns: int = 50,
    timeout_seconds: int = 60,
) -> GovernedDataQuery:
    evidence: AuditEvidencePort = (
        DelegatingAuditEvidenceAdapter(audit)
        if audit is not None
        else PublishedAuditEvidenceAdapter(session)
    )
    return GovernedDataQuery(
        catalog=catalog_adapter.SQLAlchemyDataCatalogAdapter(session),
        connector=connector_adapter.ThinkingDataConnectorAdapter(session),
        audit=evidence,
        max_rows=max_rows,
        max_columns=max_columns,
        timeout_seconds=timeout_seconds,
    )
