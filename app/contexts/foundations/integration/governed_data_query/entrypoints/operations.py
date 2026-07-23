"""Request-scoped catalog and governed-query operations."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.governance.audit_trail import public as audit_public
from app.contexts.foundations.integration.governed_data_query.contracts import (
    DataCatalogSnapshot,
    GovernedQueryRequest,
    GovernedQueryResult,
)
from app.contexts.foundations.integration.governed_data_query.infrastructure.composition import (
    build_governed_data_query,
)


async def get_catalog(session: AsyncSession) -> DataCatalogSnapshot:
    return await build_governed_data_query(session).catalog()


async def allowed_views(session: AsyncSession) -> frozenset[str]:
    return await build_governed_data_query(session).allowed_views()


async def catalog_prompt(session: AsyncSession) -> str:
    return await build_governed_data_query(session).catalog_prompt()


async def run_query(
    session: AsyncSession,
    request: GovernedQueryRequest,
    *,
    audit: audit_public.AuditEvidencePort | None = None,
    max_rows: int = 1000,
    max_columns: int = 50,
    timeout_seconds: int = 60,
) -> GovernedQueryResult:
    return await build_governed_data_query(
        session,
        audit=audit,
        max_rows=max_rows,
        max_columns=max_columns,
        timeout_seconds=timeout_seconds,
    ).run(request)
