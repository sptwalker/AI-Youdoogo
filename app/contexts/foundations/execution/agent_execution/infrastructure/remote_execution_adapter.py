"""Remote Expert execution adapter：专家平台的 HTTP 客户端半边（Phase 3 / docs/23 §6.2）。

与 ``LocalLlmAdapter`` / ``RemoteLlmAdapter`` 实现同一 ``LlmCompletionPort``，在选择器处三选一
（Branch-by-Abstraction）。**缝设在 LlmCompletionPort**：``_prepare``(prompt+知识)/``authorize``/
``record`` 全部留在本地不动，只把「跑模型」这一步改道远端专家平台。远端的独特面是「创建→流式」
两步 API + 可寻址 ``execution_id``（后续异步 step 路径的挂钩）。

线协议（docs/23）：``POST /v1/expert-executions`` → ``{execution_id}``（``stream:false`` 另回
``{content,model,usage}``）；``GET /v1/expert-executions/{id}/stream`` → SSE 帧与网关 chat-stream
逐字对齐。Envelope 同 RemoteLlmAdapter。信任边界：非 2xx / 结构不符 / SSE 非法 → 抛错，绝不静默
返回空串。日志红线（§5）：不打印 Authorization / system_prompt / user_message 明文。
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
from app.contexts.foundations.model_gateway.public import GatewayError
from app.core.config import get_settings
from app.core.internal_token import mint_internal_token
from app.core.request_context import get_trace_id

_EXPERT_AUDIENCE = "ai-expert-platform"
_CREATE_PATH = "/v1/expert-executions"
_SCHEMA_VERSION = "v1"


class ExpertPlatformError(GatewayError):
    """专家平台调用失败（连接错误、非 2xx、响应结构非法）。不吞错，交由调用方处理。

    刻意继承 ``GatewayError``——``FallbackCompletionPort`` 只捕 ``GatewayError``，继承后专家平台
    远程失败也能被同一兜底逻辑（remote→local）识别并降级，无需改动 fallback。
    """


def _default_token_minter() -> str:
    """默认令牌：C1 Internal JWT，aud=专家平台、scope=expert:execute。私钥未配则由 mint 抛错。"""
    return mint_internal_token(
        service_id="ai-youdoogo",
        audience=_EXPERT_AUDIENCE,
        scope=("expert:execute",),
    )


def _usage(raw: object) -> TokenUsage:
    """把远端 usage 段归一化为 TokenUsage；缺失/非 dict → 全零（用量非关键路径，不因缺失抛错）。"""
    if not isinstance(raw, dict):
        return TokenUsage()
    return TokenUsage(
        int(raw.get("prompt_tokens", 0) or 0),
        int(raw.get("completion_tokens", 0) or 0),
        int(raw.get("total_tokens", 0) or 0),
    )


class RemoteExpertExecutionAdapter:
    """Speak the expert platform's create→stream contract; keep transport off the port."""

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
        self._timeout = settings.expert_platform_timeout if timeout is None else timeout
        self._max_retries = (
            settings.expert_platform_max_retries if max_retries is None else max_retries
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
            raise ExpertPlatformError("专家平台 invoke 响应缺少 content 字段或结构非法")
        model = data.get("model")
        return LlmCompletionResponse(
            content=data["content"],
            model=str(model) if model is not None else None,
            usage=_usage(data.get("usage")),
        )

    def stream(self, request: LlmCompletionRequest) -> AsyncIterator[LlmCompletionStreamChunk]:
        async def _iterate() -> AsyncIterator[LlmCompletionStreamChunk]:
            # 第一步：创建执行（POST，有界重试——创建幂等、无部分产出，可安全重试）。
            created = await self._request_json(self._body(request, stream=True))
            if not isinstance(created, dict) or not isinstance(created.get("execution_id"), str):
                raise ExpertPlatformError("专家平台创建响应缺少 execution_id")
            execution_id = created["execution_id"]
            # 第二步：流式取回。SSE 已开始产出后不重试（重试会重复投递，信任边界，宁可抛错）。
            path = f"{self._base_url}{_CREATE_PATH}/{execution_id}/stream"
            headers = {**self._headers(), "Accept": "text/event-stream"}
            client = self._client or httpx.AsyncClient(timeout=self._timeout)
            try:
                async with client.stream("GET", path, headers=headers) as resp:
                    await self._raise_for_status(resp)
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

    async def _request_json(self, body: dict[str, object]) -> object:
        """POST + 有界重试（连接错误/5xx）。创建幂等：无业务副作用、无部分产出，可安全重试。"""
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        try:
            last_exc: Exception | None = None
            for attempt in range(self._max_retries + 1):
                try:
                    resp = await client.post(
                        f"{self._base_url}{_CREATE_PATH}", json=body, headers=self._headers()
                    )
                    if resp.status_code >= 500 and attempt < self._max_retries:
                        continue  # 5xx 可重试（专家平台瞬时故障）
                    await self._raise_for_status(resp)
                    return resp.json()
                except httpx.RequestError as exc:
                    last_exc = exc
                    if attempt >= self._max_retries:
                        raise ExpertPlatformError(f"专家平台请求失败：{exc}") from exc
            raise ExpertPlatformError(f"专家平台请求失败：{last_exc}")  # pragma: no cover
        finally:
            if self._client is None:
                await client.aclose()

    @staticmethod
    async def _raise_for_status(resp: httpx.Response) -> None:
        if resp.status_code >= 400:
            # 不回显 body（可能含敏感串/超长）；只带状态码，符合 §5 日志红线。
            raise ExpertPlatformError(f"专家平台返回 {resp.status_code}")


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
        raise ExpertPlatformError(f"专家平台 SSE 行非法 JSON：{payload[:80]}") from exc
    if not isinstance(obj, dict) or "delta" not in obj or "accumulated_content" not in obj:
        raise ExpertPlatformError("专家平台 SSE chunk 缺少 delta/accumulated_content 字段")
    model = obj.get("model")
    return LlmCompletionStreamChunk(
        delta=str(obj["delta"]),
        accumulated_content=str(obj["accumulated_content"]),
        model=str(model) if model is not None else None,
        usage=_usage(obj.get("usage")),
    )
