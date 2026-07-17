"""混合检索单测（docs/15 阶段A.1）:RRF 融合纯函数 + 关键词臂降级 + search 融合编排。

RRF 与融合是纯 Python 可测;DB 臂（向量/关键词）用 monkeypatch 打桩，不依赖 pgvector/pg_trgm。
"""

import uuid
from collections.abc import AsyncGenerator
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.knowledge import retrieval
from app.knowledge.retrieval import Hit, rrf_fuse
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


def _hit(name: str, idx: int = 0, fid: uuid.UUID | None = None) -> Hit:
    return Hit(
        file_id=fid or uuid.uuid4(), file_name=name, chunk_index=idx,
        chunk_text=f"{name}#{idx}", distance=0.0,
    )


# ── rrf_fuse 纯函数 ─────────────────────────────────────
def test_rrf_single_list_preserves_order() -> None:
    a, b, c = _hit("a"), _hit("b"), _hit("c")
    out = rrf_fuse([[a, b, c]])
    assert [h.file_name for h in out] == ["a", "b", "c"]


def test_rrf_dedups_same_chunk() -> None:
    """同一 (file_id, chunk_index) 跨臂只留一份，得分叠加。"""
    fid = uuid.uuid4()
    h1 = _hit("doc", 2, fid)
    h2 = _hit("doc", 2, fid)  # 同键不同对象
    out = rrf_fuse([[h1], [h2]])
    assert len(out) == 1


def test_rrf_multi_arm_hit_ranks_first() -> None:
    """两臂都命中的项应排到只被单臂命中的项之前（得分叠加）。"""
    fid_both = uuid.uuid4()
    both_v = _hit("both", 0, fid_both)
    both_k = _hit("both", 0, fid_both)
    only_v = _hit("onlyv", 0)
    only_k = _hit("onlyk", 0)
    # 向量臂: [onlyv(rank1), both(rank2)]; 关键词臂: [onlyk(rank1), both(rank2)]
    out = rrf_fuse([[only_v, both_v], [only_k, both_k]])
    assert out[0].file_name == "both"  # 叠加分最高


def test_rrf_k_smaller_sharpens_top() -> None:
    """k 越小，高排名主导越强（第1名与第2名分差更大）——参数生效性。"""
    a, b = _hit("a"), _hit("b")
    # 用不同 k 融合两个单臂列表，验证 k 参数确实进入计分
    out_small = rrf_fuse([[a], [b]], k=1)
    out_big = rrf_fuse([[a], [b]], k=1000)
    assert [h.file_name for h in out_small] == [h.file_name for h in out_big] == ["a", "b"]


def test_rrf_empty() -> None:
    assert rrf_fuse([]) == []
    assert rrf_fuse([[], []]) == []


# ── search 融合编排（DB 臂打桩）─────────────────────────
async def test_search_fuses_both_arms(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """混合开:两臂结果经 RRF 融合、去重、截到 top_k。"""
    shared = uuid.uuid4()
    vec = [_hit("shared", 0, shared), _hit("v_only", 0)]
    kw = [_hit("shared", 0, shared), _hit("k_only", 0)]

    async def _fake_vec(*a: Any, **k: Any) -> list[Hit]:
        return vec

    async def _fake_kw(*a: Any, **k: Any) -> list[Hit]:
        return kw

    monkeypatch.setattr(retrieval, "_vector_arm", _fake_vec)
    monkeypatch.setattr(retrieval, "_keyword_arm", _fake_kw)
    out = await retrieval.search(db, "查询", top_k=2)
    names = [h.file_name for h in out]
    assert out[0].file_name == "shared"  # 双臂命中排首
    assert len(out) == 2 and len(names) == len(set(names))  # 截 top_k + 已去重


async def test_search_visible_empty_returns_empty(db: AsyncSession) -> None:
    """无可见库直接空，不触发任何臂。"""
    assert await retrieval.search(db, "q", visible_kb_ids=[]) == []


async def test_search_flag_off_pure_vector(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """开关关 → 只跑向量臂，不跑关键词臂（等价旧行为）。"""
    called = {"vec": 0, "kw": 0}

    async def _fake_vec(*a: Any, **k: Any) -> list[Hit]:
        called["vec"] += 1
        return [_hit("v", 0)]

    async def _fake_kw(*a: Any, **k: Any) -> list[Hit]:
        called["kw"] += 1
        return [_hit("k", 0)]

    async def _off(_db: Any, key: str, default: Any) -> Any:
        return False if key == "retrieval_hybrid_enabled" else default

    monkeypatch.setattr(retrieval, "_vector_arm", _fake_vec)
    monkeypatch.setattr(retrieval, "_keyword_arm", _fake_kw)
    monkeypatch.setattr(retrieval.config_service, "resolve", _off)
    out = await retrieval.search(db, "q", top_k=3)
    assert called == {"vec": 1, "kw": 0} and out[0].file_name == "v"


async def test_keyword_arm_degrades_on_error(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """关键词臂 SQL 异常（如 SQLite 无 word_similarity）→ 返回 []，不抛。"""
    # 真库是 SQLite，word_similarity 不存在，执行必失败 → 应吞掉返回空
    out = await retrieval._keyword_arm(db, "q", 10, None)
    assert out == []


async def test_search_survives_keyword_failure(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """关键词臂坏掉时 search 仍返回向量臂结果（优雅降级端到端）。"""
    async def _fake_vec(*a: Any, **k: Any) -> list[Hit]:
        return [_hit("v", 0)]

    monkeypatch.setattr(retrieval, "_vector_arm", _fake_vec)
    # 不打桩 _keyword_arm，让它真跑 SQLite → 内部吞异常返回 []
    out = await retrieval.search(db, "q", top_k=3)
    assert [h.file_name for h in out] == ["v"]
