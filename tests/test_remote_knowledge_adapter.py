"""RemoteKnowledgeSearchAdapter 离线契约（Phase 2 / docs/21 §8.1、§11）。

用 httpx.MockTransport 回放知识服务 JSON，无真服务、无真 ES256 私钥（注入 stub token_minter）。
覆盖：search 归一化、envelope 头 + 请求体 shape、trace_id 透传、信任边界抛错
（非 2xx / body 缺 hits / hit 字段非法，绝不静默返回空）、5xx 有界重试、UUID 序列化/解析。
"""

from __future__ import annotations

import json
import uuid

import httpx
import pytest

from app.contexts.foundations.knowledge.knowledge_retrieval.contracts import (
    SearchKnowledgeQuery,
)
from app.contexts.foundations.knowledge.knowledge_retrieval.infrastructure.remote_adapter import (
    KnowledgeGatewayError,
    RemoteKnowledgeSearchAdapter,
)
from app.core import request_context

_BASE = "http://knowledge.test"
_KB_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
_DOC_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
_REQ = SearchKnowledgeQuery(query="季度营收", top_k=3, visible_knowledge_base_ids=(_KB_ID,))


def _adapter(handler: httpx.MockTransport, **kwargs: object) -> RemoteKnowledgeSearchAdapter:
    return RemoteKnowledgeSearchAdapter(
        base_url=_BASE,
        client=httpx.AsyncClient(transport=handler),
        token_minter=lambda: "stub-token",
        **kwargs,  # type: ignore[arg-type]
    )


def _json_handler(payload: dict[str, object], status: int = 200) -> httpx.MockTransport:
    def handle(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=payload)

    return httpx.MockTransport(handle)


def _hit(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "document_id": str(_DOC_ID),
        "document_name": "Q3财报.pdf",
        "chunk_index": 2,
        "content": "第三季度营收增长 18%。",
        "score_distance": 0.12,
        "provenance": "knowledge_index",
    }
    base.update(over)
    return base


async def test_search_normalizes_response() -> None:
    adapter = _adapter(_json_handler({"query": "季度营收", "hits": [_hit()]}))
    result = await adapter.search(_REQ)
    assert result.query == "季度营收"
    assert len(result.hits) == 1
    hit = result.hits[0]
    assert hit.document_id == _DOC_ID
    assert hit.document_name == "Q3财报.pdf"
    assert hit.chunk_index == 2
    assert hit.score_distance == pytest.approx(0.12)


async def test_search_sends_envelope_and_body() -> None:
    seen: dict[str, object] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = request.headers
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"query": "q", "hits": []})

    await _adapter(httpx.MockTransport(handle)).search(_REQ)

    assert seen["url"] == f"{_BASE}/v1/knowledge/search"
    headers = seen["headers"]
    assert headers["authorization"] == "Bearer stub-token"  # type: ignore[index]
    assert headers["x-tenant-key"] == "youdoogo"  # type: ignore[index]
    assert headers["x-caller-service"] == "ai-youdoogo"  # type: ignore[index]
    assert headers["x-schema-version"] == "v1"  # type: ignore[index]
    body = seen["body"]
    assert body["query"] == "季度营收"  # type: ignore[index]
    assert body["top_k"] == 3  # type: ignore[index]
    assert body["visible_knowledge_base_ids"] == [str(_KB_ID)]  # type: ignore[index]


async def test_search_serializes_null_visibility() -> None:
    seen: dict[str, object] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"query": "q", "hits": []})

    await _adapter(httpx.MockTransport(handle)).search(
        SearchKnowledgeQuery(query="q", top_k=5, visible_knowledge_base_ids=None)
    )
    assert seen["body"]["visible_knowledge_base_ids"] is None  # type: ignore[index]


async def test_trace_id_propagates_as_request_id() -> None:
    token = request_context._trace_id.set("trace-kb-999")
    try:
        seen: dict[str, str] = {}

        def handle(request: httpx.Request) -> httpx.Response:
            seen["rid"] = request.headers["x-request-id"]
            return httpx.Response(200, json={"query": "q", "hits": []})

        await _adapter(httpx.MockTransport(handle)).search(_REQ)
        assert seen["rid"] == "trace-kb-999"
    finally:
        request_context._trace_id.reset(token)


async def test_empty_hits_is_valid_not_error() -> None:
    # 空结果与服务故障必须可区分：空 hits 是合法的「无命中」，不抛错。
    result = await _adapter(_json_handler({"query": "q", "hits": []})).search(_REQ)
    assert result.hits == ()


async def test_search_raises_on_non_2xx() -> None:
    with pytest.raises(KnowledgeGatewayError):
        await _adapter(_json_handler({}, status=400)).search(_REQ)


async def test_search_raises_on_missing_hits() -> None:
    # 200 但缺 hits → 结构非法，抛错而非静默返回空（否则无法与「无命中」区分）。
    with pytest.raises(KnowledgeGatewayError):
        await _adapter(_json_handler({"query": "q"})).search(_REQ)


async def test_search_raises_on_malformed_hit() -> None:
    with pytest.raises(KnowledgeGatewayError):
        await _adapter(
            _json_handler({"query": "q", "hits": [_hit(document_id="not-a-uuid")]})
        ).search(_REQ)


async def test_search_retries_5xx_then_succeeds() -> None:
    calls = {"n": 0}

    def handle(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, json={"error": "busy"})
        return httpx.Response(200, json={"query": "q", "hits": [_hit()]})

    result = await _adapter(httpx.MockTransport(handle), max_retries=2).search(_REQ)
    assert len(result.hits) == 1
    assert calls["n"] == 2
