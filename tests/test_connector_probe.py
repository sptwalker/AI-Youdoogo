"""连接器连通探针单测（离线）：http_api 探针（SSRF/缺配置/HTTP 错）+ 分派表按类型选执行器。

http_api 探针经 httpx.MockTransport 离线；SSRF 经 monkeypatch net.resolve_ips 注入解析结果。
分派表验证：原生 http_api 内建、注入探针（thinkingdata）被选中、未知类型安全回落 unsupported。
"""

import uuid

import httpx
import pytest

from app.contexts.foundations.integration.connector_management.contracts import (
    ConnectorProbeResult,
    ConnectorSnapshot,
)
from app.contexts.foundations.integration.connector_management.entrypoints import probe
from app.contexts.foundations.integration.connector_management.infrastructure.http_fetch import (
    _MAX_BYTES,
    fetch_http_api,
)
from app.contexts.foundations.integration.connector_management.infrastructure.http_probe import (
    probe_http_api,
)
from app.platform import net


def _snap(
    connector_type: str,
    *,
    config: dict[str, object] | None = None,
    secret_ref: str | None = None,
) -> ConnectorSnapshot:
    return ConnectorSnapshot(
        id=uuid.uuid4(),
        name="t",
        code="t",
        connector_type=connector_type,
        department_id=None,
        config=config or {},
        secret_ref=secret_ref,
        secret_status="none",
        is_active=True,
        owner_expert_id=None,
        owner_expert_name=None,
    )


# ── http_api 探针 ────────────────────────────────────────
async def test_http_probe_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(net, "resolve_ips", lambda _host: ["93.184.216.34"])

    def _handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"pong")

    result = await probe_http_api(
        None,  # type: ignore[arg-type]
        _snap("http_api", config={"url": "https://api.example.com/health"}),
        transport=httpx.MockTransport(_handler),
    )
    assert result.status == "ok" and "HTTP 200" in result.message


async def test_http_probe_rejects_private_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(net, "resolve_ips", lambda _host: ["10.0.0.5"])
    result = await probe_http_api(
        None,  # type: ignore[arg-type]
        _snap("http_api", config={"url": "http://intranet.local/health"}),
    )
    assert result.status == "fail" and "SSRF" in result.message


async def test_http_probe_not_configured_without_url() -> None:
    result = await probe_http_api(None, _snap("http_api", config={}))  # type: ignore[arg-type]
    assert result.status == "not_configured"


async def test_http_probe_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(net, "resolve_ips", lambda _host: ["93.184.216.34"])

    def _handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    result = await probe_http_api(
        None,  # type: ignore[arg-type]
        _snap("http_api", config={"base_url": "https://api.example.com/x"}),
        transport=httpx.MockTransport(_handler),
    )
    assert result.status == "fail"  # 5xx 经 raise_for_status → 结构化 fail，不抛穿


# ── 分派表 ───────────────────────────────────────────────
async def test_dispatch_selects_native_http_api() -> None:
    """原生 http_api 内建于分派表：缺 url → not_configured（唯有 http_api 探针产出此结果）。"""
    result = await probe.probe_connector(None, _snap("http_api", config={}))  # type: ignore[arg-type]
    assert result.status == "not_configured"


async def test_dispatch_selects_injected_probe() -> None:
    async def _fake(_db: object, _c: ConnectorSnapshot) -> ConnectorProbeResult:
        return ConnectorProbeResult(status="ok", message="TD 连通", row_count=7)

    result = await probe.probe_connector(
        None,  # type: ignore[arg-type]
        _snap("thinkingdata"),
        extra_probes={"thinkingdata": _fake},
    )
    assert result.status == "ok" and result.row_count == 7


async def test_dispatch_unknown_type_unsupported() -> None:
    result = await probe.probe_connector(None, _snap("mystery"))  # type: ignore[arg-type]
    assert result.status == "unsupported" and "mystery" in result.message


# ── http_api 取数执行器（对称补全探针：探针只连通，取数带 body）───
async def test_fetch_normalises_nested_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(net, "resolve_ips", lambda _host: ["93.184.216.34"])

    def _handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"id": 1, "t": "差评爆发"}, {"id": 2}]})

    result = await fetch_http_api(
        None,  # type: ignore[arg-type]
        _snap("http_api", config={"url": "https://api.example.com/sentiment"}),
        transport=httpx.MockTransport(_handler),
    )
    assert result.status == "ok" and result.row_count == 2
    assert result.records[0]["t"] == "差评爆发"


async def test_fetch_skips_empty_first_list(monkeypatch: pytest.MonkeyPatch) -> None:
    """{"errors":[], "data":[...]} 不因 errors 空列表排在前面而丢真数据。"""
    monkeypatch.setattr(net, "resolve_ips", lambda _host: ["93.184.216.34"])

    def _handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"errors": [], "data": [{"id": 1, "t": "舆情"}]})

    result = await fetch_http_api(
        None,  # type: ignore[arg-type]
        _snap("http_api", config={"url": "https://api.example.com/sentiment"}),
        transport=httpx.MockTransport(_handler),
    )
    assert result.status == "ok" and result.row_count == 1
    assert result.records[0]["t"] == "舆情"  # 命中已知 data 键而非空 errors


async def test_fetch_wraps_bare_list_and_scalars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(net, "resolve_ips", lambda _host: ["93.184.216.34"])

    def _handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=["纯文本项", {"k": "v"}])

    result = await fetch_http_api(
        None,  # type: ignore[arg-type]
        _snap("http_api", config={"url": "https://api.example.com/x"}),
        transport=httpx.MockTransport(_handler),
    )
    assert result.row_count == 2
    assert result.records[0] == {"value": "纯文本项"}  # 标量项归一为 {value:...}


async def test_fetch_non_json_returns_text_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(net, "resolve_ips", lambda _host: ["93.184.216.34"])

    def _handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content="<html>竞品官网更新</html>".encode())

    result = await fetch_http_api(
        None,  # type: ignore[arg-type]
        _snap("http_api", config={"url": "https://competitor.example.com"}),
        transport=httpx.MockTransport(_handler),
    )
    assert result.status == "ok" and result.records == ()
    assert "竞品官网更新" in result.text


async def test_fetch_rejects_private_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(net, "resolve_ips", lambda _host: ["127.0.0.1"])
    result = await fetch_http_api(
        None,  # type: ignore[arg-type]
        _snap("http_api", config={"url": "http://localhost/metrics"}),
    )
    assert result.status == "fail" and "SSRF" in result.message


async def test_fetch_not_configured_without_url() -> None:
    result = await fetch_http_api(None, _snap("http_api", config={}))  # type: ignore[arg-type]
    assert result.status == "not_configured"


async def test_fetch_http_error_is_structured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(net, "resolve_ips", lambda _host: ["93.184.216.34"])

    def _handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    result = await fetch_http_api(
        None,  # type: ignore[arg-type]
        _snap("http_api", config={"url": "https://api.example.com/x"}),
        transport=httpx.MockTransport(_handler),
    )
    assert result.status == "fail"  # 5xx → 结构化 fail，不抛穿


async def test_fetch_caps_oversized_body(monkeypatch: pytest.MonkeyPatch) -> None:
    """上游返回超 _MAX_BYTES 的 body → 流式累计到上限即断，输出截到 _MAX_BYTES（不整页留存）。"""
    monkeypatch.setattr(net, "resolve_ips", lambda _host: ["93.184.216.34"])
    huge = b"a" * (_MAX_BYTES * 2)  # 2× 上限的非 JSON body

    def _handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=huge)

    result = await fetch_http_api(
        None,  # type: ignore[arg-type]
        _snap("http_api", config={"url": "https://competitor.example.com/dump"}),
        transport=httpx.MockTransport(_handler),
    )
    assert result.status == "ok"
    assert len(result.text.encode("utf-8")) <= _MAX_BYTES  # 输出被截，未整页留存


async def test_fetch_from_connector_rejects_non_http_api() -> None:
    from app.contexts.foundations.integration.connector_management import public

    result = await public.fetch_from_connector(None, _snap("thinkingdata"))  # type: ignore[arg-type]
    assert result.status == "fail" and "仅 http_api" in result.message
