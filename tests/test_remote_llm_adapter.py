"""RemoteLlmAdapter 离线契约（Phase 1 / docs/21 §7.1、§8.1）。

用 httpx.MockTransport 回放网关 JSON / SSE，无真服务、无真 LLM、无真 ES256 私钥
（注入 stub token_minter）。覆盖：invoke 归一化、envelope 头透传、SSE 解析与 [DONE] 忽略、
信任边界抛错（非 2xx / body 结构不符 / SSE 非法 JSON）、5xx 有界重试、trace_id 透传（C3）。
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.contexts.foundations.model_gateway.contracts.completion import (
    LlmCompletionRequest,
)
from app.contexts.foundations.model_gateway.infrastructure.remote_adapter import (
    GatewayError,
    RemoteLlmAdapter,
)
from app.core import request_context
from scripts.llm_replay import stream_is_consistent

_BASE = "http://gateway.test"
_REQ = LlmCompletionRequest(model_role="daily", system_prompt="s", user_message="u")


def _adapter(handler: httpx.MockTransport | object, **kwargs: object) -> RemoteLlmAdapter:
    client = httpx.AsyncClient(transport=handler)  # type: ignore[arg-type]
    return RemoteLlmAdapter(
        base_url=_BASE,
        client=client,
        token_minter=lambda: "stub-token",
        **kwargs,  # type: ignore[arg-type]
    )


def _json_handler(payload: dict[str, object], status: int = 200) -> httpx.MockTransport:
    def handle(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=payload)

    return httpx.MockTransport(handle)


def _sse_handler(body: str) -> httpx.MockTransport:
    def handle(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body.encode("utf-8"))

    return httpx.MockTransport(handle)


async def test_invoke_normalizes_response() -> None:
    adapter = _adapter(
        _json_handler(
            {
                "content": "网关产出",
                "model": "deepseek-chat",
                "usage": {"prompt_tokens": 5, "completion_tokens": 7, "total_tokens": 12},
            }
        )
    )
    resp = await adapter.invoke(_REQ)
    assert resp.content == "网关产出"
    assert resp.model == "deepseek-chat"
    assert (resp.usage.prompt_tokens, resp.usage.completion_tokens, resp.usage.total_tokens) == (
        5,
        7,
        12,
    )


async def test_invoke_sends_envelope_and_body() -> None:
    seen: dict[str, object] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        seen["headers"] = request.headers
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"content": "ok"})

    adapter = _adapter(httpx.MockTransport(handle))
    await adapter.invoke(_REQ)

    headers = seen["headers"]
    assert headers["authorization"] == "Bearer stub-token"  # type: ignore[index]
    assert headers["x-tenant-key"] == "youdoogo"  # type: ignore[index]
    assert headers["x-caller-service"] == "ai-youdoogo"  # type: ignore[index]
    assert headers["x-schema-version"] == "v1"  # type: ignore[index]
    body = seen["body"]
    assert body["model_role"] == "daily"  # type: ignore[index]
    assert body["stream"] is False  # type: ignore[index]


async def test_trace_id_propagates_as_request_id() -> None:
    token = request_context._trace_id.set("trace-abc12345")
    try:
        seen: dict[str, str] = {}

        def handle(request: httpx.Request) -> httpx.Response:
            seen["rid"] = request.headers["x-request-id"]
            return httpx.Response(200, json={"content": "ok"})

        await _adapter(httpx.MockTransport(handle)).invoke(_REQ)
        assert seen["rid"] == "trace-abc12345"
    finally:
        request_context._trace_id.reset(token)


async def test_stream_parses_sse_and_ignores_done() -> None:
    body = (
        'data: {"delta": "你", "accumulated_content": "你"}\n\n'
        'data: {"delta": "好", "accumulated_content": "你好"}\n\n'
        ": keep-alive\n\n"
        "data: [DONE]\n\n"
    )
    chunks = [chunk async for chunk in _adapter(_sse_handler(body)).stream(_REQ)]
    assert len(chunks) == 2
    assert stream_is_consistent(chunks)
    assert chunks[-1].accumulated_content == "你好"


async def test_invoke_raises_on_non_2xx() -> None:
    # 400 不重试；直接抛 GatewayError（信任边界）。
    with pytest.raises(GatewayError):
        await _adapter(_json_handler({}, status=400)).invoke(_REQ)


async def test_invoke_raises_on_malformed_body() -> None:
    # 200 但缺 content → 结构非法，抛错而非静默返回空串。
    with pytest.raises(GatewayError):
        await _adapter(_json_handler({"model": "m"})).invoke(_REQ)


async def test_stream_raises_on_invalid_json() -> None:
    with pytest.raises(GatewayError):
        adapter = _adapter(_sse_handler("data: not-json\n\n"))
        [chunk async for chunk in adapter.stream(_REQ)]


async def test_invoke_retries_5xx_then_succeeds() -> None:
    calls = {"n": 0}

    def handle(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, json={"error": "busy"})
        return httpx.Response(200, json={"content": "重试后成功"})

    adapter = _adapter(httpx.MockTransport(handle), max_retries=2)
    resp = await adapter.invoke(_REQ)
    assert resp.content == "重试后成功"
    assert calls["n"] == 2  # 首次 503 → 重试一次即成功
