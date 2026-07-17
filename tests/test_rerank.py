"""rerank 精排单测（docs/15 A.2）:客户端契约 + search 接入 flag 开关 + 优雅降级。

rerank 客户端用 respx 打桩 HTTP，不发真实请求;search 接入用 monkeypatch 打桩 rerank 函数。
"""

import uuid
from collections.abc import AsyncGenerator
from typing import Any

import httpx
import pytest
import respx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.knowledge import rerank, retrieval
from app.knowledge.rerank import RerankError
from app.knowledge.retrieval import Hit
from app.models import Base


@pytest.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


def _hit(name: str, idx: int = 0) -> Hit:
    return Hit(file_id=uuid.uuid4(), file_name=name, chunk_index=idx,
              chunk_text=f"{name}#{idx}", distance=0.0)


def _cfg(**over: Any) -> Any:
    """打桩 config_service.resolve：默认混合开、rerank 按传入。"""
    async def _resolve(_db: Any, key: str, default: Any) -> Any:
        return over.get(key, default)
    return _resolve


# ── rerank 客户端 ───────────────────────────────────────
def _set_cfg(monkeypatch: pytest.MonkeyPatch, **kv: str) -> None:
    from app.core import runtime_config

    monkeypatch.setattr(
        runtime_config, "effective",
        lambda key, default="": kv.get(key, default),
    )


async def test_rerank_empty_docs_returns_empty(db: AsyncSession) -> None:
    assert await rerank.rerank("q", [], top_n=5) == []


async def test_rerank_no_endpoint_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_cfg(monkeypatch)  # 无 rerank_base_url
    with pytest.raises(RerankError, match="端点"):
        await rerank.rerank("q", ["a", "b"], top_n=2)


async def test_rerank_no_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_cfg(monkeypatch, rerank_base_url="https://rr.test/v1")  # 有端点无密钥
    with pytest.raises(RerankError, match="密钥"):
        await rerank.rerank("q", ["a", "b"], top_n=2)


@respx.mock
async def test_rerank_parses_and_sorts(monkeypatch: pytest.MonkeyPatch) -> None:
    """打桩 /rerank：乱序返回 → 按分降序 + 截 top_n + 归位 index。"""
    _set_cfg(monkeypatch, rerank_base_url="https://rr.test/v1", rerank_api_key="k")
    respx.post("https://rr.test/v1/rerank").mock(
        return_value=httpx.Response(200, json={"results": [
            {"index": 0, "relevance_score": 0.1},
            {"index": 2, "relevance_score": 0.9},
            {"index": 1, "relevance_score": 0.5},
        ]})
    )
    out = await rerank.rerank("q", ["a", "b", "c"], top_n=2)
    assert out == [(2, 0.9), (1, 0.5)]  # 降序 + 截 2


@respx.mock
async def test_rerank_tolerates_score_field(monkeypatch: pytest.MonkeyPatch) -> None:
    """兼容 score / relevance_score 两种字段名。"""
    _set_cfg(monkeypatch, rerank_base_url="https://rr.test/v1", rerank_api_key="k")
    respx.post("https://rr.test/v1/rerank").mock(
        return_value=httpx.Response(200, json={"results": [{"index": 0, "score": 0.7}]})
    )
    assert await rerank.rerank("q", ["a"], top_n=1) == [(0, 0.7)]


# ── search 接入 rerank ──────────────────────────────────
async def test_search_rerank_off_skips(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """rerank 开关关（默认）→ 不调用 rerank，返回 RRF 序。"""
    called = {"n": 0}

    async def _spy(*a: Any, **k: Any) -> list[tuple[int, float]]:
        called["n"] += 1
        return []

    async def _vec(*a: Any, **k: Any) -> list[Hit]:
        return [_hit("v1"), _hit("v2")]

    monkeypatch.setattr(retrieval, "_vector_arm", _vec)
    monkeypatch.setattr(retrieval, "_keyword_arm", lambda *a, **k: _empty())
    monkeypatch.setattr(rerank, "rerank", _spy)
    monkeypatch.setattr(retrieval.config_service, "resolve", _cfg())  # rerank 默认 False
    out = await retrieval.search(db, "q", top_k=2)
    assert called["n"] == 0 and len(out) == 2


async def test_search_rerank_on_reorders(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """rerank 开 → 按 rerank 返回的顺序重排。"""
    a, b, c = _hit("A"), _hit("B"), _hit("C")

    async def _vec(*a2: Any, **k: Any) -> list[Hit]:
        return [a, b, c]

    async def _rr(query: str, docs: list[str], *, top_n: int) -> list[tuple[int, float]]:
        return [(2, 0.9), (0, 0.8), (1, 0.7)]  # 把 C 顶到第一

    monkeypatch.setattr(retrieval, "_vector_arm", _vec)
    monkeypatch.setattr(retrieval, "_keyword_arm", lambda *x, **k: _empty())
    monkeypatch.setattr(rerank, "rerank", _rr)
    monkeypatch.setattr(retrieval.config_service, "resolve",
                        _cfg(retrieval_rerank_enabled=True))
    out = await retrieval.search(db, "q", top_k=3)
    assert [h.file_name for h in out] == ["C", "A", "B"]


async def test_search_rerank_degrades_on_error(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """rerank 抛错 → 沿用 RRF 融合序，不阻断。"""
    a, b = _hit("A"), _hit("B")

    async def _vec(*x: Any, **k: Any) -> list[Hit]:
        return [a, b]

    async def _boom(*x: Any, **k: Any) -> list[tuple[int, float]]:
        raise RerankError("端点不可用")

    monkeypatch.setattr(retrieval, "_vector_arm", _vec)
    monkeypatch.setattr(retrieval, "_keyword_arm", lambda *x, **k: _empty())
    monkeypatch.setattr(rerank, "rerank", _boom)
    monkeypatch.setattr(retrieval.config_service, "resolve",
                        _cfg(retrieval_rerank_enabled=True))
    out = await retrieval.search(db, "q", top_k=2)
    assert [h.file_name for h in out] == ["A", "B"]  # 退回融合序


async def _empty() -> list[Hit]:
    return []
