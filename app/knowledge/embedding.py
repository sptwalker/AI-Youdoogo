"""通义 text-embedding-v3 客户端（OpenAI 兼容 /embeddings 端点，1024 维）。

MVP 单 provider、不做 failover（A/B 选型与降级见 docs/06 阶段1，后续增量）。
密钥走 DASHSCOPE_API_KEY（app/core/config），无密钥抛明确异常。
"""

from __future__ import annotations

import httpx

from app.core.config import get_settings
from app.llm.factory import resolve_provider_base_url
from app.models.knowledge import EMBED_DIM

_MODEL = "text-embedding-v3"
_BATCH = 10  # ponytail: 通义批量上限保守取 10，吞吐不足再调
_TIMEOUT = 30.0


class EmbeddingError(RuntimeError):
    """embedding 调用失败（未配密钥 / 接口错误 / 维度不符）。"""


def _endpoint() -> str:
    return f"{resolve_provider_base_url('qwen')}/embeddings"


async def _embed_batch(
    client: httpx.AsyncClient, texts: list[str], api_key: str
) -> list[list[float]]:
    resp = await client.post(
        _endpoint(),
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": _MODEL,
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
    """批量向量化。空列表直接返回 []；空串会被通义拒绝，调用方须先过滤。"""
    if not texts:
        return []
    api_key = get_settings().dashscope_api_key
    if not api_key:
        raise EmbeddingError("未配置 DASHSCOPE_API_KEY，无法调用通义 embedding")
    out: list[list[float]] = []
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        for i in range(0, len(texts), _BATCH):
            out.extend(await _embed_batch(client, texts[i : i + _BATCH], api_key))
    return out


async def embed_query(text: str) -> list[float]:
    """单条查询向量化。"""
    return (await embed_texts([text]))[0]
