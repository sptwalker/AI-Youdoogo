"""语义检索 + 带来源溯源的问答（对齐 docs/04 红线：数据可溯源、禁幻觉）。"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.knowledge.embedding import embed_query
from app.llm import get_llm_for_role
from app.llm.usage import extract_usage, record_usage
from app.models.knowledge import KnowledgeFile, KnowledgeVector

_SYSTEM_PROMPT = (
    "你是企业知识库问答助手。只依据【资料】中的内容回答问题，"
    "在答案中用 [编号] 标注所引用的资料来源。"
    "若资料不足以回答，直接说明「资料不足，无法回答」，禁止编造。"
)


@dataclass
class Hit:
    """一条检索命中（chunk 及其来源）。"""

    file_id: uuid.UUID
    file_name: str
    chunk_index: int
    chunk_text: str
    distance: float


async def search(
    db: AsyncSession,
    query: str,
    top_k: int = 5,
    *,
    visible_kb_ids: list[uuid.UUID] | None = None,
) -> list[Hit]:
    """向量余弦距离检索 top_k（越小越相似），过滤已删除文件/向量。

    visible_kb_ids 传入时按可见知识库范围过滤（契约② 范围隔离）；
    传 None = 不加范围过滤（内部/兼容调用）；传空列表 = 无可见库，直接返回空。
    """
    if visible_kb_ids is not None and len(visible_kb_ids) == 0:
        return []
    qvec = await embed_query(query)
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
    stmt = stmt.order_by(dist).limit(top_k)
    rows = (await db.execute(stmt)).all()
    return [
        Hit(file_id=r.file_id, file_name=r.file_name, chunk_index=r.chunk_index,
            chunk_text=r.chunk_text, distance=float(r.distance))
        for r in rows
    ]


async def answer(
    db: AsyncSession,
    query: str,
    top_k: int = 5,
    *,
    user_id: uuid.UUID | None = None,
    visible_kb_ids: list[uuid.UUID] | None = None,
) -> dict[str, Any]:
    """检索 → 拼资料 → LLM 生成带来源标注的答案。命中为空时不调用模型。

    visible_kb_ids 为请求方可见知识库范围（契约② 隔离），由 API 层按请求用户算出。
    """
    hits = await search(db, query, top_k, visible_kb_ids=visible_kb_ids)
    if not hits:
        return {"answer": "资料不足，无法回答（知识库中未检索到相关内容）。", "sources": []}

    context = "\n\n".join(f"[{i + 1}] {h.chunk_text}" for i, h in enumerate(hits))
    llm = get_llm_for_role("default", temperature=0.3)
    t0 = time.monotonic()
    reply = await llm.ainvoke(
        [
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=f"【资料】\n{context}\n\n【问题】\n{query}"),
        ]
    )
    prompt_tok, completion_tok, total_tok = extract_usage(reply)
    await record_usage(
        db, role="default", model=str(reply.response_metadata.get("model_name") or "default"),
        prompt_tokens=prompt_tok, completion_tokens=completion_tok, total_tokens=total_tok,
        duration_ms=int((time.monotonic() - t0) * 1000), user_id=user_id,
    )
    sources = [
        {"index": i + 1, "file_id": str(h.file_id), "file_name": h.file_name,
         "chunk_index": h.chunk_index}
        for i, h in enumerate(hits)
    ]
    return {"answer": reply.content, "sources": sources}
