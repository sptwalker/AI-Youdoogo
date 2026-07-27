"""Framework-independent LLM completion boundary: pure DTOs + the port protocol.

这是全系统 LLM 完成调用的正典接缝（docs/21 Phase 0）。消费方只依赖本 contracts 模块，
并经 ``app.contexts.foundations.model_gateway.public`` 获取实现；Phase 1 将在同一端口后追加
``RemoteLlmAdapter``，无需改动任何调用方。契约保持纯净：不引入任何模型框架（如 langchain）。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass(frozen=True, slots=True)
class LlmCompletionRequest:
    model_role: str
    system_prompt: str
    user_message: str
    temperature: float = 0.3


@dataclass(frozen=True, slots=True)
class LlmCompletionResponse:
    content: str
    model: str | None = None
    usage: TokenUsage = TokenUsage()


@dataclass(frozen=True, slots=True)
class LlmCompletionStreamChunk:
    delta: str
    accumulated_content: str
    model: str | None = None
    usage: TokenUsage = TokenUsage()


class LlmCompletionPort(Protocol):
    """The single remote-swappable seam for LLM completion."""

    async def invoke(self, request: LlmCompletionRequest) -> LlmCompletionResponse: ...

    def stream(
        self, request: LlmCompletionRequest
    ) -> AsyncIterator[LlmCompletionStreamChunk]: ...
