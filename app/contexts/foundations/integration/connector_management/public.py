"""Published Connector Management queries for other Context adapters."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.integration.connector_management.contracts import (
    ConnectorSnapshot,
    HttpFetchResult,
)
from app.contexts.foundations.integration.connector_management.entrypoints.operations import (
    list_connectors,
)
from app.contexts.foundations.integration.connector_management.infrastructure.http_fetch import (
    fetch_http_api,
)


async def connector_catalog(
    session: AsyncSession,
) -> tuple[ConnectorSnapshot, ...]:
    """Return immutable connector snapshots; callers cannot mutate source facts."""
    return await list_connectors(session)


async def fetch_from_connector(
    session: AsyncSession, connector: ConnectorSnapshot
) -> HttpFetchResult:
    """对 http_api 类型连接器做一次只读取数；非 http_api 类型安全回落 fail（不抛穿）。

    跨 Context 取数唯一入口（P2 舆情扫描经此拉外部数据），只读、经 SSRF 守卫、body 有上限。
    """
    if connector.connector_type != "http_api":
        return HttpFetchResult(
            status="fail",
            message=f"暂不支持 {connector.connector_type} 类型取数（仅 http_api）",
        )
    return await fetch_http_api(session, connector)
