"""Remote LLM completion adapter：LLM 网关的 HTTP 客户端半边（Phase 1 / docs/21 §7.1）。

与 ``LocalLlmAdapter`` 实现同一 ``LlmCompletionPort``，在 ``public`` 处二选一
（Branch-by-Abstraction）。对外只认网关的 JSON / SSE 契约（docs/21 §7.1）；langchain 等模型框架
留在网关内部，本客户端不感知。网关服务本体是后续独立仓库——本适配器是网关必须匹配的
**客户端契约**，用 httpx.MockTransport 离线验证。

Envelope（docs/21 §8.1）：Authorization Bearer（C1 Internal JWT）、X-Request-ID（C3 trace_id）、
X-Tenant-Key、X-Caller-Service、X-Schema-Version。信任边界：非 2xx / body 结构不符 / SSE 非法
→ 抛错，绝不静默返回空串。日志红线（§7.1）：不打印 Authorization 与 body 明文。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable

import httpx

from app.contexts.foundations.model_gateway.contracts.completion import (
    LlmCompletionRequest,
    LlmCompletionResponse,
    LlmCompletionStreamChunk,
    TokenUsage,
)
from app.core.config import get_settings
from app.core.internal_token import mint_internal_token
from app.core.request_context import get_trace_id

_GATEWAY_AUDIENCE = "ai-model-gateway"
_CHAT_PATH = "/v1/chat/completions"
_SCHEMA_VERSION = "v1"


class GatewayError(Exception):
    """网关调用失败（连接错误、非 2xx、响应结构非法）。不吞错，交由调用方处理。"""


def _default_token_minter() -> str:
    """默认令牌：C1 Internal JWT，aud=网关、scope=llm:complete。私钥未配则由 mint 抛错。"""
    return mint_internal_token(
        service_id="ai-youdoogo",
        audience=_GATEWAY_AUDIENCE,
        scope=("llm:complete",),
    )


def _usage(raw: object) -> TokenUsage:
    """把网关 usage 段归一化为 TokenUsage；缺失/非 dict → 全零（用量非关键路径，不因缺失抛错）。"""
    if not isinstance(raw, dict):
        return TokenUsage()
    return TokenUsage(
        int(raw.get("prompt_tokens", 0) or 0),
        int(raw.get("completion_tokens", 0) or 0),
        int(raw.get("total_tokens", 0) or 0),
    )


class RemoteLlmAdapter:
    """Speak the gateway's JSON/SSE contract; keep transport concerns off the port."""

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
        self._timeout = settings.llm_request_timeout if timeout is None else timeout
        self._max_retries = (
            settings.llm_gateway_max_retries if max_retries is None else max_retries
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

    def _body(self, request: LlmCompletionRequest, *, stream: bool) -> dict[str, object]:
        return {
            "model_role": request.model_role,
            "system_prompt": request.system_prompt,
            "user_message": request.user_message,
            "temperature": request.temperature,
            "stream": stream,
        }

    async def invoke(self, request: LlmCompletionRequest) -> LlmCompletionResponse:
        data = await self._request_json(self._body(request, stream=False))
        if not isinstance(data, dict) or not isinstance(data.get("content"), str):
            raise GatewayError("网关 chat 响应缺少 content 字段或结构非法")
        model = data.get("model")
        return LlmCompletionResponse(
            content=data["content"],
            model=str(model) if model is not None else None,
            usage=_usage(data.get("usage")),
        )

    def stream(
        self, request: LlmCompletionRequest
    ) -> AsyncIterator[LlmCompletionStreamChunk]:
        async def _iterate() -> AsyncIterator[LlmCompletionStreamChunk]:
            body = self._body(request, stream=True)
            headers = {**self._headers(), "Accept": "text/event-stream"}
            client = self._client or httpx.AsyncClient(timeout=self._timeout)
            try:
                # 流式不重试：SSE 已开始产出后重试会重复投递（信任边界，宁可抛错让调用方决定）。
                async with client.stream(
                    "POST", f"{self._base_url}{_CHAT_PATH}", json=body, headers=headers
                ) as resp:
                    await self._raise_for_status(resp)
                    async for line in resp.aiter_lines():
                        chunk = _parse_sse_line(line)
                        if chunk is not None:
                            yield chunk
            except httpx.RequestError as exc:
                raise GatewayError(f"网关流式请求失败：{exc}") from exc
            finally:
                if self._client is None:
                    await client.aclose()

        return _iterate()

    async def _request_json(self, body: dict[str, object]) -> object:
        """POST + 有界重试（连接错误/5xx）。非流式安全重试：无副作用、无部分产出。"""
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        try:
            last_exc: Exception | None = None
            for attempt in range(self._max_retries + 1):
                try:
                    resp = await client.post(
                        f"{self._base_url}{_CHAT_PATH}", json=body, headers=self._headers()
                    )
                    if resp.status_code >= 500 and attempt < self._max_retries:
                        continue  # 5xx 可重试（网关瞬时故障/候选切换中）
                    await self._raise_for_status(resp)
                    return resp.json()
                except httpx.RequestError as exc:
                    last_exc = exc
                    if attempt >= self._max_retries:
                        raise GatewayError(f"网关请求失败：{exc}") from exc
            raise GatewayError(f"网关请求失败：{last_exc}")  # pragma: no cover - 循环必先返回/抛
        finally:
            if self._client is None:
                await client.aclose()

    @staticmethod
    async def _raise_for_status(resp: httpx.Response) -> None:
        if resp.status_code >= 400:
            # 不回显 body（可能含敏感串/超长）；只带状态码，符合 §7.1 日志红线。
            raise GatewayError(f"网关返回 {resp.status_code}")


def _parse_sse_line(line: str) -> LlmCompletionStreamChunk | None:
    """解析一行 SSE：非 data 行/空行/keep-alive → None；[DONE] → None；否则 JSON→chunk。"""
    line = line.strip()
    if not line or not line.startswith("data:"):
        return None
    payload = line[len("data:") :].strip()
    if not payload or payload == "[DONE]":
        return None
    try:
        obj = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise GatewayError(f"网关 SSE 行非法 JSON：{payload[:80]}") from exc
    if not isinstance(obj, dict) or "delta" not in obj or "accumulated_content" not in obj:
        raise GatewayError("网关 SSE chunk 缺少 delta/accumulated_content 字段")
    model = obj.get("model")
    return LlmCompletionStreamChunk(
        delta=str(obj["delta"]),
        accumulated_content=str(obj["accumulated_content"]),
        model=str(model) if model is not None else None,
        usage=_usage(obj.get("usage")),
    )
