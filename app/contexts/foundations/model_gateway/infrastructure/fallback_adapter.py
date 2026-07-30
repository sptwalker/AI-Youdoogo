"""Remote 主、Local 兜底的完成端口（路线 A：本地为永久安全网，非过渡态）。

docs/21 步骤5 canary 期与终态皆用：``build_llm_completion_port`` 选中远程时，用本包装
远程为主、本地为兜底，把 canary 风险从 ``失败率 × 灰度比`` 压到 ~0（远程失败静默落本地）。

- invoke 无副作用——远程抛 ``GatewayError`` 即落本地。
- stream 遵循「首块前可切、已产出无法重启」（与 LocalLlmAdapter / FallbackChatModel 同义）：
  远程在产出首块前失败 → 落本地；已产出后失败 → 上抛（信任边界，不静默切本地丢半截上下文）。

每次降级 WARN 记 ``model_role`` 作远程可靠性证据；不打印 prompt/body/Authorization（§7.1 红线）。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from app.contexts.foundations.model_gateway.contracts.completion import (
    LlmCompletionPort,
    LlmCompletionRequest,
    LlmCompletionResponse,
    LlmCompletionStreamChunk,
)
from app.contexts.foundations.model_gateway.infrastructure.remote_adapter import (
    GatewayError,
)

logger = logging.getLogger(__name__)


class FallbackCompletionPort:
    """包装 primary(remote) + fallback(local)，实现 LlmCompletionPort。"""

    def __init__(
        self, *, primary: LlmCompletionPort, fallback: LlmCompletionPort
    ) -> None:
        self._primary = primary
        self._fallback = fallback

    async def invoke(
        self, request: LlmCompletionRequest
    ) -> LlmCompletionResponse:
        try:
            return await self._primary.invoke(request)
        except GatewayError as exc:
            logger.warning(
                "远程网关 invoke 失败，降级本地 model_role=%s err=%s",
                request.model_role,
                exc,
            )
            return await self._fallback.invoke(request)

    def stream(
        self, request: LlmCompletionRequest
    ) -> AsyncIterator[LlmCompletionStreamChunk]:
        async def _iterate() -> AsyncIterator[LlmCompletionStreamChunk]:
            started = False
            try:
                async for chunk in self._primary.stream(request):
                    started = True
                    yield chunk
            except GatewayError as exc:
                if started:
                    raise  # 已产出无法重启，上抛（信任边界）
                logger.warning(
                    "远程网关 stream 首块前失败，降级本地 model_role=%s err=%s",
                    request.model_role,
                    exc,
                )
                async for chunk in self._fallback.stream(request):
                    yield chunk

        return _iterate()
