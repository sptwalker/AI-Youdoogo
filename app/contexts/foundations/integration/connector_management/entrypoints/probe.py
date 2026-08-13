"""连接器连通测试分派表：按 connector_type 选执行器。

原生探针（http_api）内建于本 foundations 上下文；需业务上下文的探针（如 thinkingdata 复用运营分析）
由组合根（API 层）经 `extra_probes` 注入——foundations 不得反向依赖 business。未知类型安全回落
`unsupported`，绝不抛穿。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.integration.connector_management.contracts import (
    ConnectorProbeResult,
    ConnectorSnapshot,
)
from app.contexts.foundations.integration.connector_management.infrastructure.http_probe import (
    probe_http_api,
)

ConnectorProbe = Callable[[AsyncSession, ConnectorSnapshot], Awaitable[ConnectorProbeResult]]

_NATIVE_PROBES: dict[str, ConnectorProbe] = {"http_api": probe_http_api}


async def probe_connector(
    db: AsyncSession,
    connector: ConnectorSnapshot,
    *,
    extra_probes: Mapping[str, ConnectorProbe] | None = None,
) -> ConnectorProbeResult:
    """按 connector_type 选执行器跑一次连通测试；无匹配 → unsupported。"""
    probes: dict[str, ConnectorProbe] = {**_NATIVE_PROBES, **(extra_probes or {})}
    probe = probes.get(connector.connector_type)
    if probe is None:
        return ConnectorProbeResult(
            status="unsupported",
            message=f"暂不支持 {connector.connector_type} 类型的连通测试",
        )
    return await probe(db, connector)
