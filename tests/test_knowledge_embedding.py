"""通义 embedding 客户端单测（respx 模拟，不发真实请求）。"""

import httpx
import pytest
import respx

from app.contexts.foundations.knowledge import embedding_gateway as embedding
from app.contexts.foundations.knowledge.embedding_gateway import (
    EmbeddingError,
    embed_query,
    embed_texts,
)
from app.core.config import get_settings
from app.models.knowledge import EMBED_DIM

ENDPOINT = "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings"


@pytest.fixture(autouse=True)
def _set_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "dashscope_api_key", "test-key")


def _vec(seed: float = 0.1) -> list[float]:
    return [seed] * EMBED_DIM


def _reply(indices: list[int]) -> httpx.Response:
    return httpx.Response(
        200, json={"data": [{"index": i, "embedding": _vec()} for i in indices]}
    )


@respx.mock
async def test_embed_texts_request_shape() -> None:
    route = respx.post(ENDPOINT).mock(return_value=_reply([0, 1]))
    out = await embed_texts(["a", "b"])
    assert len(out) == 2 and all(len(v) == EMBED_DIM for v in out)
    body = route.calls.last.request.content
    assert b'"text-embedding-v3"' in body
    assert f'"dimensions": {EMBED_DIM}'.encode() in body or b'"dimensions":' in body
    assert route.calls.last.request.headers["authorization"] == "Bearer test-key"


@respx.mock
async def test_embed_query_returns_single_vector() -> None:
    respx.post(ENDPOINT).mock(return_value=_reply([0]))
    vec = await embed_query("问题")
    assert len(vec) == EMBED_DIM


@respx.mock
async def test_out_of_order_response_reordered() -> None:
    """接口乱序返回时按 index 归位。"""
    respx.post(ENDPOINT).mock(
        return_value=httpx.Response(
            200,
            json={"data": [
                {"index": 1, "embedding": _vec(0.9)},
                {"index": 0, "embedding": _vec(0.1)},
            ]},
        )
    )
    out = await embed_texts(["first", "second"])
    assert out[0][0] == 0.1 and out[1][0] == 0.9


@respx.mock
async def test_batching_over_limit() -> None:
    """超过批量上限拆多次请求。"""
    n = embedding._BATCH + 3
    route = respx.post(ENDPOINT).mock(
        side_effect=[_reply(list(range(embedding._BATCH))), _reply(list(range(3)))]
    )
    out = await embed_texts([f"t{i}" for i in range(n)])
    assert len(out) == n
    assert route.call_count == 2


@respx.mock
async def test_dimension_mismatch_raises() -> None:
    respx.post(ENDPOINT).mock(
        return_value=httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1, 0.2]}]})
    )
    with pytest.raises(EmbeddingError, match="维度"):
        await embed_texts(["x"])


async def test_empty_input_no_request() -> None:
    assert await embed_texts([]) == []


async def test_no_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "dashscope_api_key", "")
    with pytest.raises(EmbeddingError, match="DASHSCOPE"):
        await embed_texts(["x"])
