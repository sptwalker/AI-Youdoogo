"""RemoteKnowledgeIndexAdapter 离线契约 + 写侧选择器（Phase 2 / docs/21 §8.1、§11）。

用 httpx.MockTransport 回放知识服务 JSON，无真服务、无真 ES256 私钥（注入 stub token_minter）。
覆盖：index_text/list 归一化、envelope 头 + 请求体 shape、trace 透传、信任边界抛错
（非 2xx / document 字段非法）、写不重试、DELETE 幂等；选择器默认 local + 硬切换（无 canary）。
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import httpx
import pytest

from app.contexts.foundations.knowledge.knowledge_indexing import public
from app.contexts.foundations.knowledge.knowledge_indexing.contracts import IndexTextCommand
from app.contexts.foundations.knowledge.knowledge_indexing.infrastructure.local_adapter import (
    LocalKnowledgeIndexAdapter,
)
from app.contexts.foundations.knowledge.knowledge_indexing.infrastructure.remote_adapter import (
    KnowledgeIndexGatewayError,
    RemoteKnowledgeIndexAdapter,
)
from app.core import request_context
from app.core.config import Settings, get_settings

_BASE = "http://knowledge.test"
_KB_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
_DOC_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
_UP_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")
_CMD = IndexTextCommand(
    title="Q3财报", text="第三季度营收增长 18%。", uploader_id=_UP_ID, knowledge_base_id=_KB_ID
)


def _adapter(handler: httpx.MockTransport, **kwargs: object) -> RemoteKnowledgeIndexAdapter:
    return RemoteKnowledgeIndexAdapter(
        base_url=_BASE,
        client=httpx.AsyncClient(transport=handler),
        token_minter=lambda: "stub-token",
        **kwargs,  # type: ignore[arg-type]
    )


def _doc(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": str(_DOC_ID),
        "file_name": "Q3财报",
        "knowledge_base_id": str(_KB_ID),
        "category": "finance",
        "uploader_id": str(_UP_ID),
        "storage_path": "text://Q3财报",
        "file_size": 42,
        "mime_type": "text/plain",
        "status": "indexed",
        "create_time": datetime(2026, 7, 30, 8, 0, tzinfo=UTC).isoformat(),
    }
    base.update(over)
    return base


def _handler(payload: object, status: int = 200) -> httpx.MockTransport:
    def handle(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=payload)

    return httpx.MockTransport(handle)


async def test_index_text_normalizes_document() -> None:
    doc = await _adapter(_handler(_doc())).index_text(_CMD)
    assert doc.id == _DOC_ID
    assert doc.knowledge_base_id == _KB_ID
    assert doc.uploader_id == _UP_ID
    assert doc.file_size == 42
    assert doc.status == "indexed"
    assert doc.create_time.year == 2026


async def test_index_text_nullable_fields() -> None:
    doc = await _adapter(
        _handler(_doc(category=None, file_size=None, mime_type=None))
    ).index_text(_CMD)
    assert doc.category is None
    assert doc.file_size is None
    assert doc.mime_type is None


async def test_index_text_sends_envelope_and_body() -> None:
    seen: dict[str, object] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["method"] = request.method
        seen["headers"] = request.headers
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=_doc())

    await _adapter(httpx.MockTransport(handle)).index_text(
        IndexTextCommand(
            title="t", text="body", uploader_id=_UP_ID, knowledge_base_id=_KB_ID,
            category="c", document_id=_DOC_ID,
        )
    )
    assert seen["url"] == f"{_BASE}/v1/documents"
    assert seen["method"] == "POST"
    headers = seen["headers"]
    assert headers["authorization"] == "Bearer stub-token"  # type: ignore[index]
    assert headers["x-tenant-key"] == "youdoogo"  # type: ignore[index]
    assert headers["x-schema-version"] == "v1"  # type: ignore[index]
    body = seen["body"]
    assert body["title"] == "t"  # type: ignore[index]
    assert body["text"] == "body"  # type: ignore[index]
    assert body["uploader_id"] == str(_UP_ID)  # type: ignore[index]
    assert body["knowledge_base_id"] == str(_KB_ID)  # type: ignore[index]
    assert body["category"] == "c"  # type: ignore[index]
    assert body["document_id"] == str(_DOC_ID)  # type: ignore[index]


async def test_trace_id_propagates_as_request_id() -> None:
    token = request_context._trace_id.set("trace-idx-777")
    try:
        seen: dict[str, str] = {}

        def handle(request: httpx.Request) -> httpx.Response:
            seen["rid"] = request.headers["x-request-id"]
            return httpx.Response(200, json=_doc())

        await _adapter(httpx.MockTransport(handle)).index_text(_CMD)
        assert seen["rid"] == "trace-idx-777"
    finally:
        request_context._trace_id.reset(token)


async def test_list_documents_normalizes() -> None:
    adapter = _adapter(_handler({"documents": [_doc(), _doc(id=str(uuid.uuid4()))]}))
    result = await adapter.list_documents(limit=10)
    assert len(result) == 2


async def test_list_documents_sends_limit() -> None:
    seen: dict[str, str] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"documents": []})

    await _adapter(httpx.MockTransport(handle)).list_documents(limit=7)
    assert seen["url"] == f"{_BASE}/v1/documents?limit=7"


async def test_remove_is_idempotent_delete() -> None:
    seen: dict[str, str] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["method"] = request.method
        return httpx.Response(204)

    await _adapter(httpx.MockTransport(handle)).remove_document_index(_DOC_ID)
    assert seen["method"] == "DELETE"
    assert seen["url"] == f"{_BASE}/v1/documents/{_DOC_ID}/index"


async def test_index_raises_on_non_2xx() -> None:
    with pytest.raises(KnowledgeIndexGatewayError):
        await _adapter(_handler({}, status=500)).index_text(_CMD)


async def test_index_raises_on_malformed_document() -> None:
    with pytest.raises(KnowledgeIndexGatewayError):
        await _adapter(_handler(_doc(id="not-a-uuid"))).index_text(_CMD)


async def test_write_does_not_retry_on_5xx() -> None:
    calls = {"n": 0}

    def handle(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503, json={"error": "busy"})

    with pytest.raises(KnowledgeIndexGatewayError):
        await _adapter(httpx.MockTransport(handle)).index_text(_CMD)
    assert calls["n"] == 1  # 写副作用不重试（无 idempotency_key）


# === 写侧选择器（build_knowledge_index_port）===


def _settings(**over: object) -> Settings:
    base = dict(knowledge_index_mode="local", knowledge_gateway_url="")
    base.update(over)
    return Settings(**base)  # type: ignore[arg-type]


class _StubSession:
    """LocalKnowledgeIndexAdapter 仅构造期存 session；选择器测试不触写。"""


@pytest.fixture(autouse=True)
def _clear() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_selector_local_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(public, "get_settings", lambda: _settings())
    port = public.build_knowledge_index_port(_StubSession())  # type: ignore[arg-type]
    assert isinstance(port, LocalKnowledgeIndexAdapter)


def test_selector_remote_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(public, "get_settings", lambda: _settings(
        knowledge_index_mode="remote", knowledge_gateway_url="http://kb:8080"))
    port = public.build_knowledge_index_port(_StubSession())  # type: ignore[arg-type]
    assert isinstance(port, RemoteKnowledgeIndexAdapter)


def test_selector_remote_mode_without_url_rejected() -> None:
    with pytest.raises(ValueError, match="KNOWLEDGE_INDEX_MODE"):
        _settings(knowledge_index_mode="remote", knowledge_gateway_url="")
