"""知识库 embedding 客户端（OpenAI 兼容 /embeddings 端点，1024 维）。

A/B 可配置（docs/06 阶段1）：默认通义 text-embedding-v3；经 .env 的
EMBEDDING_BASE_URL / EMBEDDING_MODEL / EMBEDDING_API_KEY 可替换为 bge-m3 等
（须仍为 1024 维，否则要改 knowledge_vector.embedding 列并重建 hnsw 索引）。
密钥留空则回退 DASHSCOPE_API_KEY；无密钥抛明确异常。
"""

from __future__ import annotations

import httpx

from app.core.config import get_settings
from app.llm.factory import resolve_provider_base_url
from app.models.knowledge import EMBED_DIM

_BATCH = 10  # ponytail: 批量上限保守取 10，吞吐不足再调
_TIMEOUT = 30.0


class EmbeddingError(RuntimeError):
    """embedding 调用失败（未配密钥 / 接口错误 / 维度不符）。"""


def _base_url() -> str:
    """embedding 端点根地址：配置优先，留空回退通义。"""
    return get_settings().embedding_base_url or resolve_provider_base_url("qwen") or ""


def _endpoint() -> str:
    return f"{_base_url()}/embeddings"


def _api_key() -> str:
    s = get_settings()
    return s.embedding_api_key or s.dashscope_api_key


async def _embed_batch(
    client: httpx.AsyncClient, texts: list[str], api_key: str
) -> list[list[float]]:
    resp = await client.post(
        _endpoint(),
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": get_settings().embedding_model,
            "input": texts,
            "dimensions": EMBED_DIM,
            "encoding_format": "float",
        },
    )
    resp.raise_for_status()
    data = resp.json().get("data", [])
    if len(data) != len(texts):
        raise EmbeddingError(f"embedding 返回条数 {len(data)} 与输入 {len(texts)} 不符")
    # 按 index 归位（接口可能乱序返回）
    ordered = sorted(data, key=lambda d: d["index"])
    vectors = [d["embedding"] for d in ordered]
    for v in vectors:
        if len(v) != EMBED_DIM:
            raise EmbeddingError(f"embedding 维度 {len(v)} 与预期 {EMBED_DIM} 不符")
    return vectors


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """批量向量化。空列表直接返回 []；空串会被端点拒绝，调用方须先过滤。"""
    if not texts:
        return []
    api_key = _api_key()
    if not api_key:
        raise EmbeddingError("未配置 embedding 密钥（EMBEDDING_API_KEY 或 DASHSCOPE_API_KEY）")
    out: list[list[float]] = []
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        for i in range(0, len(texts), _BATCH):
            out.extend(await _embed_batch(client, texts[i : i + _BATCH], api_key))
    return out


async def embed_query(text: str) -> list[float]:
    """单条查询向量化。"""
    return (await embed_texts([text]))[0]
