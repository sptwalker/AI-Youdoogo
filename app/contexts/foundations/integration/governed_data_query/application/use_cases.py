"""Governed catalog and read-only query use cases."""

from __future__ import annotations

from app.contexts.foundations.integration.governed_data_query.application.catalog_policy import (
    render_catalog_prompt,
)
from app.contexts.foundations.integration.governed_data_query.application.contracts import (
    QueryAuditEvidence,
)
from app.contexts.foundations.integration.governed_data_query.application.ports import (
    AuditEvidencePort,
    ConnectorExecutionFailure,
    ConnectorExecutionPort,
    DataCatalogPort,
)
from app.contexts.foundations.integration.governed_data_query.application.sql_guard import (
    SqlRejected,
    check_sql,
)
from app.contexts.foundations.integration.governed_data_query.contracts import (
    DataCatalogSnapshot,
    GovernedQueryRequest,
    GovernedQueryResult,
)


class GovernedDataQuery:
    def __init__(
        self,
        *,
        catalog: DataCatalogPort,
        connector: ConnectorExecutionPort,
        audit: AuditEvidencePort,
        max_rows: int = 1000,
        max_columns: int = 50,
        timeout_seconds: int = 60,
    ) -> None:
        self._catalog = catalog
        self._connector = connector
        self._audit = audit
        self._max_rows = max_rows
        self._max_columns = max_columns
        self._timeout_seconds = timeout_seconds

    async def catalog(self) -> DataCatalogSnapshot:
        return await self._catalog.snapshot()

    async def allowed_views(self) -> frozenset[str]:
        return (await self.catalog()).allowed_views

    async def catalog_prompt(self) -> str:
        return render_catalog_prompt(await self.catalog())

    async def run(self, request: GovernedQueryRequest) -> GovernedQueryResult:
        try:
            safe_sql = check_sql(
                request.sql,
                allowed_views=set(await self.allowed_views()),
                max_limit=self._max_rows,
            )
        except SqlRejected as exc:
            await self._record(request, request.sql, "rejected", {"reason": str(exc)})
            return GovernedQueryResult(status="rejected", reason=str(exc))

        configuration = await self._connector.configuration()
        if not configuration.base_url or not configuration.api_secret:
            return GovernedQueryResult(status="fail", message="未配置 TD 地址/密钥")

        try:
            raw_rows = await self._connector.execute(
                configuration,
                safe_sql,
                timeout=self._timeout_seconds,
            )
        except ConnectorExecutionFailure as exc:
            message = str(exc)[:200]
            await self._record(request, safe_sql, "fail", {"msg": message})
            return GovernedQueryResult(status="fail", message=message)

        truncated = len(raw_rows) > self._max_rows
        raw_rows = raw_rows[: self._max_rows]
        columns = tuple(raw_rows[0].keys())[: self._max_columns] if raw_rows else ()
        rows = tuple({column: row.get(column) for column in columns} for row in raw_rows)
        await self._record(request, safe_sql, "ok", {"row_count": len(rows)})
        return GovernedQueryResult(
            status="ok",
            columns=columns,
            rows=rows,
            row_count=len(rows),
            truncated=truncated,
        )

    async def _record(
        self,
        request: GovernedQueryRequest,
        sql: str,
        result: str,
        detail: dict[str, object],
    ) -> None:
        await self._audit.record(
            QueryAuditEvidence(
                actor_id=request.actor_id,
                actor_role=request.actor_role,
                sql=sql,
                source=request.source,
                result=result,
                detail=detail,
            )
        )
