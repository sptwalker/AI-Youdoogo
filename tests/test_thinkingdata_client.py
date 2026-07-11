"""ThinkingData 客户端单测（respx 模拟，不发真实请求）。"""

import json

import httpx
import pytest
import respx

from app.integrations.thinkingdata import ThinkingDataClient, ThinkingDataError

BASE = "http://td.test:8992"


def _client() -> ThinkingDataClient:
    return ThinkingDataClient(base_url=BASE, api_secret="test-secret", retry_base_delay=0.01)


def _ndjson(meta: dict, rows: list) -> str:
    return "\n".join([json.dumps(meta), *(json.dumps(r) for r in rows)])


@respx.mock
async def test_query_sql_ok() -> None:
    meta = {"data": {"headers": ["dt", "dau"]}, "return_code": 0, "return_message": "success"}
    rows = [{"dt": "2026-07-11", "dau": 1234}, {"dt": "2026-07-12", "dau": 1300}]
    route = respx.post(f"{BASE}/querySql").mock(
        return_value=httpx.Response(200, text=_ndjson(meta, rows))
    )

    got = await _client().query_sql("SELECT dt, dau FROM v_event_1")
    assert got == rows
    # token 在 URL 参数中传递
    assert route.calls.last.request.url.params["token"] == "test-secret"
    assert route.calls.last.request.url.params["format"] == "json_object"


@respx.mock
async def test_rate_limit_retry_then_ok() -> None:
    limited = {"return_code": -1005, "return_message": "请求频率过快"}
    ok_meta = {"data": {"headers": ["n"]}, "return_code": 0}
    route = respx.post(f"{BASE}/querySql").mock(
        side_effect=[
            httpx.Response(200, text=json.dumps(limited)),
            httpx.Response(200, text=_ndjson(ok_meta, [{"n": 1}])),
        ]
    )

    got = await _client().query_sql("SELECT 1")
    assert got == [{"n": 1}]
    assert route.call_count == 2


@respx.mock
async def test_error_code_raises() -> None:
    err = {"return_code": -1008, "return_message": "参数(token)为空"}
    respx.post(f"{BASE}/querySql").mock(return_value=httpx.Response(200, text=json.dumps(err)))

    with pytest.raises(ThinkingDataError) as exc_info:
        await _client().query_sql("SELECT 1")
    assert exc_info.value.return_code == -1008


@respx.mock
async def test_iter_sql_rows_two_pages() -> None:
    submit_meta = {
        "data": {"headers": ["n"], "pageCount": 2, "pageSize": 1000, "taskId": "t-123"},
        "return_code": 0,
    }
    page_meta = {"data": {"headers": ["n"]}, "return_code": 0}
    respx.post(f"{BASE}/open/execute-sql").mock(
        return_value=httpx.Response(200, text=json.dumps(submit_meta))
    )
    page_route = respx.get(f"{BASE}/open/sql-result-page").mock(
        side_effect=[
            httpx.Response(200, text=_ndjson(page_meta, [{"n": 1}, {"n": 2}])),
            httpx.Response(200, text=_ndjson(page_meta, [{"n": 3}])),
        ]
    )

    rows = [r async for r in _client().iter_sql_rows("SELECT n FROM big", page_size=1000)]
    assert rows == [{"n": 1}, {"n": 2}, {"n": 3}]
    assert page_route.call_count == 2
    assert page_route.calls[0].request.url.params["pageId"] == "0"
    assert page_route.calls[1].request.url.params["taskId"] == "t-123"


async def test_unconfigured_raises() -> None:
    client = ThinkingDataClient(base_url="", api_secret="")
    with pytest.raises(ThinkingDataError, match="TD_BASE_URL"):
        await client.query_sql("SELECT 1")


@respx.mock
async def test_error_message_never_contains_token() -> None:
    """网络错误的异常文本不得泄露 token（httpx 原始异常含完整 URL）。"""
    respx.post(f"{BASE}/querySql").mock(side_effect=httpx.ConnectError("boom"))

    with pytest.raises(ThinkingDataError) as exc_info:
        await _client().query_sql("SELECT 1")
    assert "test-secret" not in str(exc_info.value)
