"""http_api 连接器连通探针（读侧 GET，只探连通、不取业务数据）。

外部可控 URL → 连接前必过 SSRF 校验（复用 platform.net）；bearer 走 runtime_config，绝不硬编码；
禁自动重定向；stream 读首块即断不整页进内存。任何 httpx 错只记 host + `type(exc).__name__`、返
结构化 fail、不抛穿。无状态、无 DB 依赖（形参 `_db` 仅为与分派表签名对齐）。
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.integration.connector_management.contracts import (
    ConnectorProbeResult,
    ConnectorSnapshot,
)
from app.core import runtime_config
from app.platform import net

logger = logging.getLogger(__name__)

_TIMEOUT = 15


async def probe_http_api(
    _db: AsyncSession,
    connector: ConnectorSnapshot,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> ConnectorProbeResult:
    """GET 连接器配置的 url，2xx 即连通。SSRF 命中/缺 url/httpx 错 → 结构化 fail。"""
    url = str(connector.config.get("url") or connector.config.get("base_url") or "").strip()
    if not url:
        return ConnectorProbeResult(
            status="not_configured", message="未配置 url（连接器参数填写 url 或 base_url）"
        )
    safe, reason = net.url_is_safe(url)
    if not safe:
        return ConnectorProbeResult(status="fail", message=reason)
    headers = {}
    if connector.secret_ref:
        token = str(runtime_config.effective(connector.secret_ref, "") or "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"
    try:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, transport=transport, follow_redirects=False
        ) as client:
            async with client.stream("GET", url, headers=headers) as response:
                response.raise_for_status()
                async for _chunk in response.aiter_bytes():
                    break  # 只验连通 + 首块可读，不累计整页
                return ConnectorProbeResult(
                    status="ok", message=f"连通正常（HTTP {response.status_code}）"
                )
    except httpx.HTTPError as exc:
        # 不复用 str(exc)：httpx 异常文本可能含带 token 的完整 URL
        logger.warning(
            "http_api 连通测试失败 host=%s err=%s",
            urlparse(url).hostname,
            type(exc).__name__,
        )
        return ConnectorProbeResult(status="fail", message=f"连通失败（{type(exc).__name__}）")


# ponytail: 探针只做「GET 首块 + 2xx」连通判定，不解析 body、不取业务数据；真正的取数执行器
#   待上游数据契约（分页/字段映射）确定后再建，当前 YAGNI。stream 读首块即断，超大页面不进内存。
