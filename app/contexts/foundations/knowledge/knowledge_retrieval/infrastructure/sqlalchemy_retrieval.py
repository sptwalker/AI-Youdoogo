"""SQLAlchemy hybrid retrieval and cited answering implementation.

混合检索（docs/15 阶段A.1）:search() = 向量臂 + 关键词臂(pg_trgm) 并发召回 → RRF 融合 → top_k。
- 向量臂:pgvector 余弦距离，擅长模糊语义。
- 关键词臂:pg_trgm word_similarity，擅长专名/产品型号/精确编码/错别字。
- 融合:倒数排名融合 RRF（无参稳健，纯函数可测）。
优雅降级:开关关 / 关键词臂异常（SQLite/无 pg_trgm）→ 自动退回纯向量，不阻断。
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.governance.usage_budget.public import record_usage
from app.contexts.foundations.knowledge import embedding_gateway
from app.contexts.foundations.knowledge.knowledge_retrieval.infrastructure import rerank_gateway
from app.contexts.foundations.knowledge.knowledge_retrieval.infrastructure.configuration import (
    resolve as resolve_config,
)
from app.contexts.foundations.knowledge.semantic_catalog.public import (
    expand_query as expand_semantic_query,
)
from app.contexts.foundations.model_gateway.contracts.completion import (
    LlmCompletionPort,
    LlmCompletionRequest,
)
from app.contexts.foundations.model_gateway.public import build_llm_completion_port
from app.models.knowledge import KnowledgeFile, KnowledgeVector

logger = logging.getLogger(__name__)


class _ConfigurationFacade:
    resolve = staticmethod(resolve_config)


# Compatibility seam: existing callers patch retrieval.config_service.resolve.
config_service = _ConfigurationFacade()

_SYSTEM_PROMPT = (
    "你是企业知识库问答助手。只依据【资料】中的内容回答问题，"
    "在答案中用 [编号] 标注所引用的资料来源。"
    "若资料不足以回答，直接说明「资料不足，无法回答」，禁止编造。"
)

_DEFAULT_RRF_K = 60  # RRF 常数：越大越弱化高排名的主导，60 为文献常用稳健默认
_DEFAULT_CAND_MULT = 4  # 每臂候选数 = max(top_k * 本倍数, 下限)
_MIN_CANDIDATES = 20
_DEFAULT_RERANK_POOL = 20  # rerank 精排的候选池上限（融合后取前 N 送 rerank，再截 top_k）


@dataclass
class Hit:
    """一条检索命中（chunk 及其来源）。distance 供展示/调试；融合排序按 RRF 分，非 distance。"""

    file_id: uuid.UUID
    file_name: str
    chunk_index: int
    chunk_text: str
    distance: float


def _hit_key(h: Hit) -> tuple[uuid.UUID, int]:
    """chunk 唯一标识（跨臂去重用）:同一文件同一块即同一命中。"""
    return (h.file_id, h.chunk_index)


def rrf_fuse(
    ranked_lists: Sequence[Sequence[Hit]],
    *,
    k: int = _DEFAULT_RRF_K,
    key: Callable[[Hit], Any] = _hit_key,
) -> list[Hit]:
    """倒数排名融合（Reciprocal Rank Fusion）——纯函数，无 DB 依赖，可单测。

    每臂产出有序列表;某命中的融合分 = Σ 1/(k + 该臂内排名)，排名从 1 起（越靠前贡献越大）。
    多臂命中的项得分叠加而排到前面。去重保留首个出现的 Hit 对象。
    """
    scores: dict[Any, float] = {}
    reps: dict[Any, Hit] = {}
    for lst in ranked_lists:
        for rank, item in enumerate(lst):
            kk = key(item)
            scores[kk] = scores.get(kk, 0.0) + 1.0 / (k + rank + 1)
            reps.setdefault(kk, item)
    ordered = sorted(scores, key=lambda kk: scores[kk], reverse=True)
    return [reps[kk] for kk in ordered]


async def _vector_arm(
    db: AsyncSession, query: str, n: int, visible_kb_ids: list[uuid.UUID] | None
) -> list[Hit]:
    """向量臂:pgvector 余弦距离升序 top_n（越小越相似）。异常向上传播（向量为主臂）。"""
    qvec = await embedding_gateway.embed_query(query)
    dist = KnowledgeVector.embedding.cosine_distance(qvec)
    stmt = (
        select(
            KnowledgeVector.file_id,
            KnowledgeFile.file_name,
            KnowledgeVector.chunk_index,
            KnowledgeVector.chunk_text,
            dist.label("distance"),
        )
        .join(KnowledgeFile, KnowledgeFile.id == KnowledgeVector.file_id)
        .where(KnowledgeFile.is_delete.is_(False), KnowledgeVector.is_delete.is_(False))
    )
    if visible_kb_ids is not None:
        stmt = stmt.where(KnowledgeFile.knowledge_base_id.in_(visible_kb_ids))
    stmt = stmt.order_by(dist).limit(n)
    rows = (await db.execute(stmt)).all()
    return [
        Hit(
            file_id=r.file_id,
            file_name=r.file_name,
            chunk_index=r.chunk_index,
            chunk_text=r.chunk_text,
            distance=float(r.distance),
        )
        for r in rows
    ]


async def _keyword_arm(
    db: AsyncSession, query: str, n: int, visible_kb_ids: list[uuid.UUID] | None
) -> list[Hit]:
    """关键词臂:pg_trgm word_similarity 降序 top_n（越大越相似）。

    优雅降级:SQLite/无 pg_trgm/任何异常 → 返回 []（不阻断，search 退化为纯向量）。
    distance 用 1 - sim 作伪距离仅供展示;融合排序按 RRF 分，与此无关。
    """
    try:
        sim = func.word_similarity(query, KnowledgeVector.chunk_text)
        stmt = (
            select(
                KnowledgeVector.file_id,
                KnowledgeFile.file_name,
                KnowledgeVector.chunk_index,
                KnowledgeVector.chunk_text,
                sim.label("sim"),
            )
            .join(KnowledgeFile, KnowledgeFile.id == KnowledgeVector.file_id)
            .where(KnowledgeFile.is_delete.is_(False), KnowledgeVector.is_delete.is_(False))
        )
        if visible_kb_ids is not None:
            stmt = stmt.where(KnowledgeFile.knowledge_base_id.in_(visible_kb_ids))
        stmt = stmt.where(sim > 0).order_by(sim.desc()).limit(n)
        rows = (await db.execute(stmt)).all()
        return [
            Hit(
                file_id=r.file_id,
                file_name=r.file_name,
                chunk_index=r.chunk_index,
                chunk_text=r.chunk_text,
                distance=float(1.0 - r.sim),
            )
            for r in rows
        ]
    except Exception:  # noqa: BLE001 - 关键词臂故障不连累检索，退化为纯向量
        logger.warning("关键词臂检索失败，本次退化为纯向量", exc_info=True)
        return []


async def diagnostic_arms(
    db: AsyncSession,
    query: str,
    top_n: int,
    visible_kb_ids: list[uuid.UUID] | None,
) -> tuple[list[Hit], list[Hit]]:
    """Published-adapter hook for side-by-side vector/keyword diagnostics."""
    if visible_kb_ids is not None and not visible_kb_ids:
        return [], []
    vector_hits = await _vector_arm(db, query, top_n, visible_kb_ids)
    keyword_hits = await _keyword_arm(db, query, top_n, visible_kb_ids)
    return vector_hits, keyword_hits


async def _hybrid_on(db: AsyncSession) -> bool:
    flag = await config_service.resolve(db, "retrieval_hybrid_enabled", True)
    return str(flag).lower() not in ("false", "0")


async def _rerank_on(db: AsyncSession) -> bool:
    flag = await config_service.resolve(db, "retrieval_rerank_enabled", False)
    return str(flag).lower() in ("true", "1")


async def _int_config(db: AsyncSession, key: str, default: int) -> int:
    try:
        return int(await config_service.resolve(db, key, default))
    except (TypeError, ValueError):
        return default


async def _maybe_rerank(db: AsyncSession, query: str, fused: list[Hit], top_k: int) -> list[Hit]:
    """对 RRF 融合结果做 cross-encoder 精排（A.2）。异常/未配 → 沿用融合序，不阻断。

    只把融合后前 pool 个候选送 rerank（控体积/成本），精排后返回;失败原样退回。
    """
    if not fused:
        return fused
    pool = await _int_config(db, "retrieval_rerank_pool", _DEFAULT_RERANK_POOL)
    cand = fused[:pool]
    try:
        order = await rerank_gateway.rerank(query, [h.chunk_text for h in cand], top_n=len(cand))
    except Exception:  # noqa: BLE001 - rerank 故障不连累检索，退回 RRF 融合序
        logger.warning("rerank 精排失败，沿用 RRF 融合序", exc_info=True)
        return fused
    if not order:
        return fused
    return [cand[i] for i, _ in order if 0 <= i < len(cand)]


async def search(
    db: AsyncSession,
    query: str,
    top_k: int = 5,
    *,
    visible_kb_ids: list[uuid.UUID] | None = None,
) -> list[Hit]:
    """混合检索 top_k:向量臂 + 关键词臂并发召回 → RRF 融合 →（可选）rerank 精排。

    签名对调用方保持不变。visible_kb_ids 传入时按可见知识库范围过滤（契约② 范围隔离）；
    传 None = 不加范围过滤（内部/兼容调用）；传空列表 = 无可见库，直接返回空。
    开关 retrieval_hybrid_enabled 关 → 纯向量;retrieval_rerank_enabled 开 → 融合后再精排。
    """
    if visible_kb_ids is not None and len(visible_kb_ids) == 0:
        return []

    if not await _hybrid_on(db):
        return await _vector_arm(db, query, top_k, visible_kb_ids)

    cand_n = max(top_k * _DEFAULT_CAND_MULT, _MIN_CANDIDATES)
    cand_n = await _int_config(db, "retrieval_candidate_n", cand_n)
    # 语义层查询扩展（docs/15 §4.2）:别名→规范名+同义词，仅喂关键词臂（向量臂语义已覆盖）。
    # 字典为空 → expand_query 原样返回，等价无扩展（优雅降级，无需开关）。
    kw_query = await expand_semantic_query(db, query)
    # 向量臂异常向上传播（主臂）；关键词臂内部已吞异常返回 []
    vec, kw = await asyncio.gather(
        _vector_arm(db, query, cand_n, visible_kb_ids),
        _keyword_arm(db, kw_query, cand_n, visible_kb_ids),
    )
    k = await _int_config(db, "retrieval_rrf_k", _DEFAULT_RRF_K)
    fused = rrf_fuse([vec, kw], k=k)
    if await _rerank_on(db):
        fused = await _maybe_rerank(db, query, fused, top_k)
    return fused[:top_k]


async def answer(
    db: AsyncSession,
    query: str,
    top_k: int = 5,
    *,
    user_id: uuid.UUID | None = None,
    visible_kb_ids: list[uuid.UUID] | None = None,
    port: LlmCompletionPort | None = None,
) -> dict[str, Any]:
    """检索 → 拼资料 → LLM 生成带来源标注的答案。命中为空时不调用模型。

    visible_kb_ids 为请求方可见知识库范围（契约② 隔离），由 API 层按请求用户算出。
    port 可注入（默认本地端口）——LLM 完成统一经 model_gateway 接缝，便于远端切换与测试替身。
    """
    hits = await search(db, query, top_k, visible_kb_ids=visible_kb_ids)
    if not hits:
        return {"answer": "资料不足，无法回答（知识库中未检索到相关内容）。", "sources": []}

    context = "\n\n".join(f"[{i + 1}] {h.chunk_text}" for i, h in enumerate(hits))
    port = port or build_llm_completion_port()
    t0 = time.monotonic()
    resp = await port.invoke(
        LlmCompletionRequest(
            model_role="default",
            system_prompt=_SYSTEM_PROMPT,
            user_message=f"【资料】\n{context}\n\n【问题】\n{query}",
            temperature=0.3,
        )
    )
    await record_usage(
        db,
        role="default",
        model=resp.model or "default",
        prompt_tokens=resp.usage.prompt_tokens,
        completion_tokens=resp.usage.completion_tokens,
        total_tokens=resp.usage.total_tokens,
        duration_ms=int((time.monotonic() - t0) * 1000),
        user_id=user_id,
    )
    sources = [
        {
            "index": i + 1,
            "file_id": str(h.file_id),
            "file_name": h.file_name,
            "chunk_index": h.chunk_index,
            "snippet": h.chunk_text,
        }
        for i, h in enumerate(hits)
    ]
    return {"answer": resp.content, "sources": sources}
