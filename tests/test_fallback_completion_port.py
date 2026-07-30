"""FallbackCompletionPort（路线 A：remote→local 兜底）行为契约。

无真服务/真 LLM——用最小 stub port。覆盖四态：远程好则透传；远程 invoke 抛错落本地；
远程 stream 首块前抛错落本地（全部来自本地）；远程 stream 已产出后抛错上抛（不静默切本地）。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from app.contexts.foundations.model_gateway.contracts.completion import (
    LlmCompletionRequest,
    LlmCompletionResponse,
    LlmCompletionStreamChunk,
)
from app.contexts.foundations.model_gateway.infrastructure.fallback_adapter import (
    FallbackCompletionPort,
)
from app.contexts.foundations.model_gateway.infrastructure.remote_adapter import (
    GatewayError,
)

_REQ = LlmCompletionRequest(model_role="daily", system_prompt="", user_message="hi")


class _Local:
    async def invoke(self, request: LlmCompletionRequest) -> LlmCompletionResponse:
        return LlmCompletionResponse(content="local", model="local-m")

    def stream(
        self, request: LlmCompletionRequest
    ) -> AsyncIterator[LlmCompletionStreamChunk]:
        async def it() -> AsyncIterator[LlmCompletionStreamChunk]:
            yield LlmCompletionStreamChunk(delta="lo", accumulated_content="lo")
            yield LlmCompletionStreamChunk(delta="cal", accumulated_content="local")

        return it()


class _RemoteOK:
    async def invoke(self, request: LlmCompletionRequest) -> LlmCompletionResponse:
        return LlmCompletionResponse(content="remote", model="remote-m")

    def stream(
        self, request: LlmCompletionRequest
    ) -> AsyncIterator[LlmCompletionStreamChunk]:
        async def it() -> AsyncIterator[LlmCompletionStreamChunk]:
            yield LlmCompletionStreamChunk(delta="re", accumulated_content="re")

        return it()


class _RemoteFailBeforeChunk:
    async def invoke(self, request: LlmCompletionRequest) -> LlmCompletionResponse:
        raise GatewayError("down")

    def stream(
        self, request: LlmCompletionRequest
    ) -> AsyncIterator[LlmCompletionStreamChunk]:
        async def it() -> AsyncIterator[LlmCompletionStreamChunk]:
            raise GatewayError("down")
            yield  # pragma: no cover  # 使 it() 成为 async generator

        return it()


class _RemoteFailMidStream:
    async def invoke(self, request: LlmCompletionRequest) -> LlmCompletionResponse:
        raise GatewayError("down")

    def stream(
        self, request: LlmCompletionRequest
    ) -> AsyncIterator[LlmCompletionStreamChunk]:
        async def it() -> AsyncIterator[LlmCompletionStreamChunk]:
            yield LlmCompletionStreamChunk(delta="re", accumulated_content="re")
            raise GatewayError("mid")

        return it()


async def test_invoke_passthrough_when_remote_ok() -> None:
    port = FallbackCompletionPort(primary=_RemoteOK(), fallback=_Local())
    assert (await port.invoke(_REQ)).content == "remote"


async def test_invoke_falls_back_on_gateway_error() -> None:
    port = FallbackCompletionPort(primary=_RemoteFailBeforeChunk(), fallback=_Local())
    assert (await port.invoke(_REQ)).content == "local"


async def test_stream_falls_back_before_first_chunk() -> None:
    port = FallbackCompletionPort(primary=_RemoteFailBeforeChunk(), fallback=_Local())
    chunks = [c async for c in port.stream(_REQ)]
    assert [c.delta for c in chunks] == ["lo", "cal"]  # 全部来自本地


async def test_stream_reraises_after_first_chunk() -> None:
    port = FallbackCompletionPort(primary=_RemoteFailMidStream(), fallback=_Local())
    got: list[str] = []
    with pytest.raises(GatewayError):
        async for c in port.stream(_REQ):
            got.append(c.delta)
    assert got == ["re"]  # 已产出首块保留，之后上抛（不静默切本地丢半截上下文）
