"""Remote Expert prepare adapter：Module 2 远端「拥有 _prepare」的 HTTP 客户端半边（docs/23 §6.2）。

与模块 1 ``RemoteExpertExecutionAdapter`` 的区别：模块 1 缝在 ``LlmCompletionPort``（prepare 留
本地，远端只跑模型）；本适配器面向**富执行端点** ``POST /v1/experts/{id}/executions``——把已本地
解析好的 ``knowledge_base_ids``/``global_prompt``/``term_prompt`` + **转发令牌**随体传远端，由远端
组装 prompt、扇出知识 Search、回流 ``sources``。随后 ``GET /v1/expert-executions/{id}/stream``
取 delta（帧复用模块 1 ``_parse_sse_line``）。

令牌：Authorization = 本服务身份令牌（aud=专家平台, scope=expert:execute）；body 内
``knowledge_token`` = **转发令牌**（aud=知识服务, scope=knowledge:search, actor=真人），私钥只在
本服务，远端不签名。日志红线（§5）：只记状态码，不打印 Authorization / token / user_message 明文。
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable

import httpx

from app.contexts.foundations.execution.agent_execution.contracts.execution import (
    LlmStreamChunk,
    SourceReference,
)
from app.contexts.foundations.execution.agent_execution.infrastructure.remote_execution_adapter import (  # noqa: E501
    ExpertPlatformError,
    _parse_sse_line,
)
from app.core.config import get_settings
from app.core.internal_token import mint_internal_token
from app.core.request_context import get_trace_id

_EXPERT_AUDIENCE = "ai-expert-platform"
_SCHEMA_VERSION = "v1"


def _default_token_minter() -> str:
    """默认令牌：Internal JWT，aud=专家平台、scope=expert:execute。私钥未配则由 mint 抛错。"""
    return mint_internal_token(
        service_id="ai-youdoogo",
        audience=_EXPERT_AUDIENCE,
        scope=("expert:execute",),
    )


def _parse_sources(raw: object) -> tuple[SourceReference, ...]:
    """把远端 sources 段归一化为 SourceReference 元组；结构非法 → 抛错（不静默丢弃）。"""
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ExpertPlatformError("专家平台 sources 非 list")
    out: list[SourceReference] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ExpertPlatformError("专家平台 source 非 dict")
        try:
            out.append(
                SourceReference(
                    file_id=str(item["document_id"]),
                    file_name=str(item["document_name"]),
                    chunk_index=int(item["chunk_index"]),
                )
            )
        except (KeyError, ValueError, TypeError) as exc:
            raise ExpertPlatformError(f"专家平台 source 字段缺失或非法：{exc}") from exc
    return tuple(out)


class RemoteExpertPrepareAdapter:
    """Speak the expert platform's rich prepare→stream contract; keep transport off the app."""

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
        self._timeout = settings.expert_platform_timeout if timeout is None else timeout

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token_minter()}",
            "X-Request-ID": get_trace_id(),
            "X-Tenant-Key": self._tenant_key,
            "X-Caller-Service": self._caller_service,
            "X-Schema-Version": _SCHEMA_VERSION,
            "Content-Type": "application/json",
        }

    async def create(
        self,
        expert_id: str,
        *,
        model_role: str,
        user_message: str,
        use_knowledge: bool,
        knowledge_base_ids: list[str] | None,
        knowledge_token: str | None,
        global_prompt: str,
        term_prompt: str,
        temperature: float = 0.3,
        gateway_token: str | None = None,
    ) -> tuple[str, tuple[SourceReference, ...]]:
        """创建远端执行（远端做组装 + 知识扇出）→ ``(execution_id, sources)``。"""
        body: dict[str, object] = {
            "model_role": model_role,
            "user_message": user_message,
            "temperature": temperature,
            "stream": True,
            "use_knowledge": use_knowledge,
            "knowledge_base_ids": knowledge_base_ids,
            "knowledge_token": knowledge_token,
            "global_prompt": global_prompt,
            "term_prompt": term_prompt,
            "gateway_token": gateway_token,  # 转发令牌（aud=网关）；None → 远端回落 echo
        }
        path = f"{self._base_url}/v1/experts/{expert_id}/executions"
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        try:
            resp = await client.post(path, json=body, headers=self._headers())
        except httpx.RequestError as exc:
            raise ExpertPlatformError(f"专家平台请求失败：{exc}") from exc
        finally:
            if self._client is None:
                await client.aclose()
        if resp.status_code >= 400:
            raise ExpertPlatformError(f"专家平台返回 {resp.status_code}")
        data = resp.json()
        if not isinstance(data, dict) or not isinstance(data.get("execution_id"), str):
            raise ExpertPlatformError("专家平台创建响应缺少 execution_id")
        return data["execution_id"], _parse_sources(data.get("sources"))

    def stream(self, execution_id: str) -> AsyncIterator[LlmStreamChunk]:
        """按 execution_id 取回 delta 流（帧复用模块 1 ``_parse_sse_line``）。"""

        async def _iterate() -> AsyncIterator[LlmStreamChunk]:
            path = f"{self._base_url}/v1/expert-executions/{execution_id}/stream"
            headers = {**self._headers(), "Accept": "text/event-stream"}
            client = self._client or httpx.AsyncClient(timeout=self._timeout)
            try:
                async with client.stream("GET", path, headers=headers) as resp:
                    if resp.status_code >= 400:
                        raise ExpertPlatformError(f"专家平台返回 {resp.status_code}")
                    async for line in resp.aiter_lines():
                        chunk = _parse_sse_line(line)
                        if chunk is not None:
                            yield chunk
            except httpx.RequestError as exc:
                raise ExpertPlatformError(f"专家平台流式请求失败：{exc}") from exc
            finally:
                if self._client is None:
                    await client.aclose()

        return _iterate()
