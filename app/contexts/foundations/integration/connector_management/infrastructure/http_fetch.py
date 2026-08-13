"""http_api 连接器只读取数执行器（读侧 GET/POST，取回并归一业务数据）。

对称补全 http_probe（探针只验连通、不取 body）：本执行器取回响应体并归一为结构化记录。
安全同探针：外部可控 URL 连接前必过 SSRF 校验（复用 platform.net）；bearer 走 runtime_config
绝不硬编码；禁自动重定向；响应体有大小上限（防超大页面撑爆内存），日志只记 host + 异常类名。
无状态、无 DB 依赖（形参 `_db` 仅为与调用签名对齐）。取回的正文是外部不可信资料——本层只取数，
下游喂 LLM 前须自行防注入 fence 包裹（P2 事件链的既有铁律）。
"""

from __future__ import annotations

import json
import logging
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.integration.connector_management.contracts import (
    ConnectorSnapshot,
    HttpFetchResult,
)
from app.core import runtime_config
from app.platform import net

logger = logging.getLogger(__name__)

_TIMEOUT = 20
_MAX_BYTES = 512 * 1024  # 512KB 上限：舆情/资讯 REST 页足够，超大页面截断不整页进内存
_MAX_RECORDS = 200


def _normalise(payload: Any) -> tuple[dict[str, Any], ...]:
    """把已解析 JSON 归一为 dict 记录列表：list[dict] 原样、list 包裹、dict 单条、其它空。

    常见舆情/资讯 API 形如 {"data":[...]} 或 {"items":[...]} → 下探业务数据 list；纯列表直接用。
    选 list 的优先级：已知数据键(data/items/results/records) > 首个非空 list > 首个 list。
    避免 {"errors":[],"data":[...]} 这类响应因 errors 空列表排在前面而丢掉真数据（仍误报 ok）。
    """
    if isinstance(payload, list):
        rows: list[Any] = payload
    elif isinstance(payload, dict):
        lists = [v for v in payload.values() if isinstance(v, list)]
        known = next(
            (payload[k] for k in ("data", "items", "results", "records")
             if isinstance(payload.get(k), list)),
            None,
        )
        nested = known or next((v for v in lists if v), None) or (lists[0] if lists else None)
        rows = nested if nested is not None else [payload]
    else:
        return ()
    records = [row if isinstance(row, dict) else {"value": row} for row in rows]
    return tuple(records[:_MAX_RECORDS])


async def fetch_http_api(
    _db: AsyncSession,
    connector: ConnectorSnapshot,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> HttpFetchResult:
    """按配置 GET/POST 外部 API 取回响应体并归一。缺 url/SSRF 命中/httpx 错 → 结构化 fail。"""
    url = str(connector.config.get("url") or connector.config.get("base_url") or "").strip()
    if not url:
        return HttpFetchResult(
            status="not_configured", message="未配置 url（连接器参数填写 url 或 base_url）"
        )
    safe, reason = net.url_is_safe(url)
    if not safe:
        return HttpFetchResult(status="fail", message=reason)
    method = str(connector.config.get("method") or "GET").strip().upper()
    if method not in ("GET", "POST"):
        method = "GET"
    headers: dict[str, str] = {}
    if connector.secret_ref:
        token = str(runtime_config.effective(connector.secret_ref, "") or "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"
    body = connector.config.get("body") if method == "POST" else None
    try:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, transport=transport, follow_redirects=False
        ) as client:
            response = await client.request(
                method,
                url,
                headers=headers,
                json=body if isinstance(body, (dict, list)) else None,
            )
            response.raise_for_status()
            raw = response.content[:_MAX_BYTES]
    except httpx.HTTPError as exc:
        # 不复用 str(exc)：httpx 异常文本可能含带 token 的完整 URL
        logger.warning(
            "http_api 取数失败 host=%s err=%s",
            urlparse(url).hostname,
            type(exc).__name__,
        )
        return HttpFetchResult(status="fail", message=f"取数失败（{type(exc).__name__}）")
    text = raw.decode("utf-8", errors="replace")
    try:
        records = _normalise(json.loads(text))
    except (json.JSONDecodeError, ValueError):
        records = ()  # 非 JSON → 只回文本预览，由下游按纯文本处理
    return HttpFetchResult(
        status="ok",
        message=f"取数成功（{len(records)} 条记录）",
        records=records,
        text=text,
    )


# ponytail: 只做「一次请求 + JSON 首层 list 归一 + 文本兜底」；分页/增量游标/厂商专用字段映射
#   待接真实上游舆情系统、数据契约确定后再加（YAGNI）。响应体 512KB 截断，超大页不进内存。
