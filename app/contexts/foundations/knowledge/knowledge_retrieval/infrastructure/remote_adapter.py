"""Remote Knowledge Search adapter：ai-knowledge-service 的 HTTP 客户端半边（Phase 2）。

docs/21 §11「先切只读 Search」。
与 ``LocalKnowledgeSearchAdapter`` 实现同一 ``KnowledgeSearchPort``，在 ``public`` 处二选一
（Branch-by-Abstraction）。端口签名会话无关——远程不传 session；数据可见性经请求体
``visible_knowledge_base_ids`` + 令牌租户维度（X-Tenant-Key）传递。知识服务本体是后续增量
（独立仓 ``ai-knowledge-service``）；本适配器即它必须匹配的**客户端契约**，用 httpx.MockTransport
离线验证（消费者驱动契约，同 Phase 1 ``RemoteLlmAdapter``）。

线协议（本适配器定义，知识服务须逐字匹配）：
- ``POST /v1/knowledge/search``
- Envelope（docs/21 §8.1）：Authorization Bearer（Internal JWT，scope=knowledge:search）、
  X-Request-ID（trace）、X-Tenant-Key、X-Caller-Service、X-Schema-Version。
- 请求体：``{query, top_k, visible_knowledge_base_ids: [uuid str] | null}``
- 响应体：``{query, hits: [{document_id, document_name, chunk_index, content,
  score_distance, provenance}]}``

信任边界（检索质量红线）：非 2xx / body 结构非法 → 抛 ``KnowledgeGatewayError``，
**绝不静默返回空 hits**（否则「无结果」与「服务故障」不可区分）。Search 幂等只读 →
连接错误 / 5xx 有界重试。日志红线（§7.1）：不打印 Authorization 与 body 明文。
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

import httpx

from app.contexts.foundations.knowledge.knowledge_retrieval.contracts import (
    KnowledgeHit,
    SearchKnowledgeQuery,
    SearchKnowledgeResult,
)
from app.core.config import get_settings
from app.core.internal_token import mint_internal_token
from app.core.request_context import get_trace_id

_KNOWLEDGE_AUDIENCE = "ai-knowledge-service"
_SEARCH_PATH = "/v1/knowledge/search"
_SCHEMA_VERSION = "v1"


class KnowledgeGatewayError(Exception):
    """知识服务调用失败（连接错误、非 2xx、响应结构非法）。不吞错，交由调用方处理。"""


def _default_token_minter() -> str:
    """默认令牌：Internal JWT，aud=知识服务、scope=knowledge:search。私钥未配则由 mint 抛错。"""
    return mint_internal_token(
        service_id="ai-youdoogo",
        audience=_KNOWLEDGE_AUDIENCE,
        scope=("knowledge:search",),
    )


def _parse_hit(raw: object) -> KnowledgeHit:
    """把一条 hit dict 归一化为 KnowledgeHit；结构非法 → 抛错（不静默丢弃损坏结果）。"""
    if not isinstance(raw, dict):
        raise KnowledgeGatewayError("知识服务 hit 非 dict")
    try:
        return KnowledgeHit(
            document_id=uuid.UUID(str(raw["document_id"])),
            document_name=str(raw["document_name"]),
            chunk_index=int(raw["chunk_index"]),
            content=str(raw["content"]),
            score_distance=float(raw["score_distance"]),
            provenance=str(raw.get("provenance", "knowledge_index")),
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise KnowledgeGatewayError(f"知识服务 hit 字段缺失或非法：{exc}") from exc


class RemoteKnowledgeSearchAdapter:
    """Speak the knowledge service's search JSON contract; keep transport off the port."""

    def __init__(
        self,
        *,
        base_url: str,
        client: httpx.AsyncClient | None = None,
        token_minter: Callable[[], str] = _default_token_minter,
        tenant_key: str = "youdoogo",
        caller_service: str = "ai-youdoogo",
        timeout: float | None = None,
        max_retries: int | None = None,
    ) -> None:
        settings = get_settings()
        self._base_url = base_url.rstrip("/")
        self._client = client  # 可注入（离线测试）；None → 每次现开一次性 client
        self._token_minter = token_minter
        self._tenant_key = tenant_key
        self._caller_service = caller_service
        self._timeout = settings.knowledge_gateway_timeout if timeout is None else timeout
        self._max_retries = (
            settings.knowledge_gateway_max_retries if max_retries is None else max_retries
        )

    def _headers(self) -> dict[str, str]:
        # Envelope（§8.1）。Authorization 承载服务身份；X-Request-ID 贯通调用链。
        return {
            "Authorization": f"Bearer {self._token_minter()}",
            "X-Request-ID": get_trace_id(),
            "X-Tenant-Key": self._tenant_key,
            "X-Caller-Service": self._caller_service,
            "X-Schema-Version": _SCHEMA_VERSION,
            "Content-Type": "application/json",
        }

    def _body(self, query: SearchKnowledgeQuery) -> dict[str, object]:
        ids = query.visible_knowledge_base_ids
        return {
            "query": query.query,
            "top_k": query.top_k,
            "visible_knowledge_base_ids": [str(i) for i in ids] if ids is not None else None,
        }

    async def search(self, query: SearchKnowledgeQuery) -> SearchKnowledgeResult:
        data = await self._request_json(self._body(query))
        if not isinstance(data, dict) or not isinstance(data.get("hits"), list):
            raise KnowledgeGatewayError("知识服务 search 响应缺少 hits 字段或结构非法")
        hits = tuple(_parse_hit(h) for h in data["hits"])
        return SearchKnowledgeResult(hits=hits, query=str(data.get("query", query.query)))

    async def _request_json(self, body: dict[str, object]) -> object:
        """POST + 有界重试（连接错误/5xx）。Search 幂等只读，无副作用可安全重试。"""
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        try:
            last_exc: Exception | None = None
            for attempt in range(self._max_retries + 1):
                try:
                    resp = await client.post(
                        f"{self._base_url}{_SEARCH_PATH}", json=body, headers=self._headers()
                    )
                    if resp.status_code >= 500 and attempt < self._max_retries:
                        continue  # 5xx 可重试（服务瞬时故障）
                    await self._raise_for_status(resp)
                    return resp.json()
                except httpx.RequestError as exc:
                    last_exc = exc
                    if attempt >= self._max_retries:
                        raise KnowledgeGatewayError(f"知识服务请求失败：{exc}") from exc
            raise KnowledgeGatewayError(f"知识服务请求失败：{last_exc}")  # pragma: no cover
        finally:
            if self._client is None:
                await client.aclose()

    @staticmethod
    async def _raise_for_status(resp: httpx.Response) -> None:
        if resp.status_code >= 400:
            # 不回显 body（可能含敏感串/超长）；只带状态码，符合 §7.1 日志红线。
            raise KnowledgeGatewayError(f"知识服务返回 {resp.status_code}")
