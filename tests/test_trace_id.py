"""trace_id 中间件/清洗/日志 filter 测试（信任边界 + 关联链路）。"""

from __future__ import annotations

import logging

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from app.core.request_context import (
    TraceIdLogFilter,
    TraceIdMiddleware,
    _sanitize,
    get_trace_id,
)


def test_sanitize_rejects_untrusted_ids() -> None:
    assert _sanitize(b"abc12345") == "abc12345"  # 合法回显
    assert _sanitize(b"short") == ""  # 太短
    assert _sanitize(b"x" * 65) == ""  # 太长
    assert _sanitize(b"bad id\nINJECT") == ""  # 空格/换行 → 拒（防日志注入）
    assert _sanitize(None) == ""
    assert _sanitize("tést-header".encode()) == ""  # 非 ascii


def _app() -> Starlette:
    async def echo(_request: object) -> PlainTextResponse:
        return PlainTextResponse(get_trace_id())

    app = Starlette(routes=[Route("/", echo)])
    app.add_middleware(TraceIdMiddleware)
    return app


@pytest.mark.anyio
async def test_middleware_generates_and_echoes_header() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=_app()), base_url="http://t"
    ) as client:
        resp = await client.get("/")
        generated = resp.headers["x-request-id"]
        assert resp.text == generated  # contextvar 贯穿到 handler
        assert len(generated) == 32  # uuid4 hex

        echoed = await client.get("/", headers={"x-request-id": "trace-abcd"})
        assert echoed.headers["x-request-id"] == "trace-abcd"
        assert echoed.text == "trace-abcd"

        forged = await client.get("/", headers={"x-request-id": "no"})
        assert forged.headers["x-request-id"] != "no"  # 非法输入被换成生成值


def test_log_filter_injects_trace_id() -> None:
    record = logging.LogRecord("n", logging.INFO, __file__, 1, "m", None, None)
    assert TraceIdLogFilter().filter(record) is True
    assert record.trace_id == "-"  # 请求外默认
