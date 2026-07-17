"""知识库 rerank 客户端（cross-encoder 精排，标准 /rerank 端点）。

混合检索 A.2（docs/15）:RRF 融合后 top_n → rerank 精排 → 最终 top_k。
默认关（retrieval_rerank_enabled=false）;开启须配 rerank 端点/密钥/模型。
端点契约取业界通用 /rerank（Jina / TEI / bge-reranker / SiliconFlow 风格）:
    POST {base}/rerank  {"model", "query", "documents": [str], "top_n": int}
    → {"results": [{"index": int, "relevance_score": float}, ...]}
密钥留空回退 DASHSCOPE_API_KEY;未配端点/密钥 → 抛 RerankError（调用方吞掉降级）。

配置键（sys_config 覆盖 → .env，同 embedding 覆盖层）:
    rerank_base_url / rerank_api_key / rerank_model
"""

from __future__ import annotations

import httpx

_TIMEOUT = 30.0
_DEFAULT_MODEL = "gte-rerank-v2"  # 占位默认;默认关，开启时由 rerank_model 覆盖为实际服务模型


class RerankError(RuntimeError):
    """rerank 调用失败（未配端点/密钥 / 接口错误）。"""


def _base_url() -> str:
    from app.core import runtime_config

    return str(runtime_config.effective("rerank_base_url", "") or "")


def _api_key() -> str:
    from app.core import runtime_config

    return str(
        runtime_config.effective("rerank_api_key", "")
        or runtime_config.effective("dashscope_api_key", "")
        or ""
    )


def _model() -> str:
    from app.core import runtime_config

    return str(runtime_config.effective("rerank_model", "") or _DEFAULT_MODEL)


async def rerank(query: str, documents: list[str], *, top_n: int) -> list[tuple[int, float]]:
    """对候选文档按与 query 的相关性精排。

    Returns:
        [(原始下标, 相关性分)] 按分降序，长度 ≤ top_n。documents 空 → []。
    Raises:
        RerankError: 未配端点/密钥；HTTP 错误由 httpx 抛出（调用方统一吞掉降级）。
    """
    if not documents:
        return []
    base = _base_url()
    if not base:
        raise RerankError("未配置 rerank 端点（rerank_base_url）")
    key = _api_key()
    if not key:
        raise RerankError("未配置 rerank 密钥（rerank_api_key 或 DASHSCOPE_API_KEY）")
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            f"{base}/rerank",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": _model(), "query": query, "documents": documents, "top_n": top_n},
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
    # relevance_score / score 两种字段名都容忍（不同服务命名不一）
    out = [
        (int(r["index"]), float(r.get("relevance_score", r.get("score", 0.0))))
        for r in results
        if isinstance(r.get("index"), int)
    ]
    out.sort(key=lambda x: x[1], reverse=True)
    return out[:top_n]
