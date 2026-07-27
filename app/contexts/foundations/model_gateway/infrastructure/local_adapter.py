"""Local (in-process) LLM completion adapter backed by the LangChain gateway.

本地实现：把 langchain 的消息类型隔离在本文件内，对外只暴露纯 ``LlmCompletion*`` 契约。
Phase 1 的 ``RemoteLlmAdapter`` 将实现同一 ``LlmCompletionPort``，两者在 ``public`` 处二选一。
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import Any, cast

from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    SystemMessage,
)

from app.contexts.foundations.model_gateway.contracts.completion import (
    LlmCompletionRequest,
    LlmCompletionResponse,
    LlmCompletionStreamChunk,
    TokenUsage,
)


def _message_text(message: AIMessage | AIMessageChunk) -> str:
    content = message.content
    return content if isinstance(content, str) else str(content)


def _prompt_messages(request: LlmCompletionRequest) -> list[BaseMessage]:
    # ponytail: 空白 system_prompt 不前置 SystemMessage，让纯探测保持 [HumanMessage] 的旧 wire 行为
    messages: list[BaseMessage] = []
    if request.system_prompt.strip():
        messages.append(SystemMessage(content=request.system_prompt))
    messages.append(HumanMessage(content=request.user_message))
    return messages


class LocalLlmAdapter:
    """Keep vendor message types outside the published completion contract."""

    def __init__(
        self,
        *,
        llm_factory: Callable[..., Any],
        usage_extractor: Callable[[Any], tuple[int, int, int]],
    ) -> None:
        self._llm_factory = llm_factory
        self._usage_extractor = usage_extractor

    async def invoke(self, request: LlmCompletionRequest) -> LlmCompletionResponse:
        llm = self._llm_factory(request.model_role, temperature=request.temperature)
        reply = await llm.ainvoke(_prompt_messages(request))
        prompt, completion, total = self._usage_extractor(reply)
        return LlmCompletionResponse(
            content=_message_text(reply),
            model=str(reply.response_metadata.get("model_name") or request.model_role),
            usage=TokenUsage(prompt, completion, total),
        )

    def stream(
        self, request: LlmCompletionRequest
    ) -> AsyncIterator[LlmCompletionStreamChunk]:
        async def _iterate() -> AsyncIterator[LlmCompletionStreamChunk]:
            llm = self._llm_factory(request.model_role, temperature=request.temperature)
            full: AIMessageChunk | None = None
            async for chunk in llm.astream(_prompt_messages(request)):
                if not isinstance(chunk, AIMessageChunk):
                    continue
                full = chunk if full is None else cast(AIMessageChunk, full + chunk)
                prompt, completion, total = self._usage_extractor(full)
                yield LlmCompletionStreamChunk(
                    delta=_message_text(chunk),
                    accumulated_content=_message_text(full),
                    model=str(
                        full.response_metadata.get("model_name") or request.model_role
                    ),
                    usage=TokenUsage(prompt, completion, total),
                )

        return _iterate()
