"""Remote Knowledge Index adapter：ai-knowledge-service 写侧 HTTP 客户端半边（Phase 2）。

docs/21 §11「先切只读 Search，再切新文档写入」+ backlog B「index 远端 adapter 本体仍属 Phase 2」。
与 ``LocalKnowledgeIndexAdapter`` 实现同一 ``KnowledgeIndexPort``，在 ``public`` 处二选一
（Branch-by-Abstraction）。端口签名会话无关——远程不传 session。本适配器即知识服务写侧
必须匹配的**客户端契约**，用 httpx.MockTransport 离线验证（消费者驱动契约，同只读 Search 侧）。

线协议（本适配器定义，知识服务须逐字匹配）：
- ``POST /v1/documents``：登记并索引文本 → 返回 IndexedDocument JSON。
- ``DELETE /v1/documents/{id}/index``：移除文档索引（幂等，已删返 2xx）。
- ``GET /v1/documents?limit=N``：列文档 → ``{documents: [IndexedDocument...]}``。
- Envelope（§8.1）：Authorization Bearer（Internal JWT，scope=knowledge:index）、X-Request-ID、
  X-Tenant-Key、X-Caller-Service、X-Schema-Version。
- IndexedDocument JSON：``{id, file_name, knowledge_base_id, category, uploader_id,
  storage_path, file_size, mime_type, status, create_time(ISO)}``。

信任边界：非 2xx / body 结构非法 → 抛 ``KnowledgeIndexGatewayError``，不静默吞错。
写是副作用：**不重试**（IndexTextCommand 无 idempotency_key，重试可能重复建文档）；连接错误直接抛。
日志红线（§7.1）：不打印 Authorization 与 body 明文。
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime

import httpx

from app.contexts.foundations.knowledge.knowledge_indexing.contracts import (
    IndexedDocument,
    IndexTextCommand,
)
from app.core.config import get_settings
from app.core.internal_token import mint_internal_token
from app.core.request_context import get_trace_id

_KNOWLEDGE_AUDIENCE = "ai-knowledge-service"
_DOCUMENTS_PATH = "/v1/documents"
_SCHEMA_VERSION = "v1"


class KnowledgeIndexGatewayError(Exception):
    """知识服务写侧调用失败（连接错误、非 2xx、响应结构非法）。不吞错，交由调用方处理。"""


def _default_token_minter() -> str:
    """默认令牌：Internal JWT，aud=知识服务、scope=knowledge:index。私钥未配则由 mint 抛错。"""
    return mint_internal_token(
        service_id="ai-youdoogo",
        audience=_KNOWLEDGE_AUDIENCE,
        scope=("knowledge:index",),
    )


def _opt_int(raw: object) -> int | None:
    return None if raw is None else int(str(raw))


def _opt_str(raw: object) -> str | None:
    return None if raw is None else str(raw)


def _parse_document(raw: object) -> IndexedDocument:
    """把一条 document dict 归一化为 IndexedDocument；结构非法 → 抛错（不静默丢弃）。"""
    if not isinstance(raw, dict):
        raise KnowledgeIndexGatewayError("知识服务 document 非 dict")
    try:
        return IndexedDocument(
            id=uuid.UUID(str(raw["id"])),
            file_name=str(raw["file_name"]),
            knowledge_base_id=uuid.UUID(str(raw["knowledge_base_id"])),
            category=_opt_str(raw.get("category")),
            uploader_id=uuid.UUID(str(raw["uploader_id"])),
            storage_path=str(raw["storage_path"]),
            file_size=_opt_int(raw.get("file_size")),
            mime_type=_opt_str(raw.get("mime_type")),
            status=str(raw["status"]),
            create_time=datetime.fromisoformat(str(raw["create_time"])),
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise KnowledgeIndexGatewayError(f"知识服务 document 字段缺失或非法：{exc}") from exc


class RemoteKnowledgeIndexAdapter:
    """Speak the knowledge service's write JSON contract; keep transport off the port."""

    def __init__(
        self,
        *,
        base_url: str,
        client: httpx.AsyncClient | None = None,
        token_minter: Callable[[], str] = _default_token_minter,
        tenant_key: str = "youdoogo",
        caller_service: str = "ai-youdoogo",
        timeout: float | None = None,
    ) -> None:
        settings = get_settings()
        self._base_url = base_url.rstrip("/")
        self._client = client  # 可注入（离线测试）；None → 每次现开一次性 client
        self._token_minter = token_minter
        self._tenant_key = tenant_key
        self._caller_service = caller_service
        self._timeout = settings.knowledge_gateway_timeout if timeout is None else timeout

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token_minter()}",
            "X-Request-ID": get_trace_id(),
            "X-Tenant-Key": self._tenant_key,
            "X-Caller-Service": self._caller_service,
            "X-Schema-Version": _SCHEMA_VERSION,
            "Content-Type": "application/json",
        }

    async def index_text(self, command: IndexTextCommand) -> IndexedDocument:
        body: dict[str, object] = {
            "title": command.title,
            "text": command.text,
            "uploader_id": str(command.uploader_id),
            "knowledge_base_id": str(command.knowledge_base_id),
            "category": command.category,
            "document_id": None if command.document_id is None else str(command.document_id),
        }
        data = await self._request(
            "POST", _DOCUMENTS_PATH, json=body, expect_json=True
        )
        return _parse_document(data)

    async def remove_document_index(self, document_id: uuid.UUID) -> None:
        # 幂等移除：服务对已删文档也应返 2xx。
        await self._request(
            "DELETE", f"{_DOCUMENTS_PATH}/{document_id}/index", expect_json=False
        )

    async def list_documents(self, *, limit: int = 100) -> tuple[IndexedDocument, ...]:
        data = await self._request(
            "GET", f"{_DOCUMENTS_PATH}?limit={limit}", expect_json=True
        )
        if not isinstance(data, dict) or not isinstance(data.get("documents"), list):
            raise KnowledgeIndexGatewayError("知识服务 list 响应缺少 documents 字段或结构非法")
        return tuple(_parse_document(d) for d in data["documents"])

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, object] | None = None,
        expect_json: bool,
    ) -> object:
        """单次请求，无重试（写副作用，无 idempotency_key 不可安全重试）。"""
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        try:
            try:
                resp = await client.request(
                    method, f"{self._base_url}{path}", json=json, headers=self._headers()
                )
            except httpx.RequestError as exc:
                raise KnowledgeIndexGatewayError(f"知识服务请求失败：{exc}") from exc
            if resp.status_code >= 400:
                # 不回显 body（可能含敏感串/超长）；只带状态码，符合 §7.1 日志红线。
                raise KnowledgeIndexGatewayError(f"知识服务返回 {resp.status_code}")
            return resp.json() if expect_json else None
        finally:
            if self._client is None:
                await client.aclose()
