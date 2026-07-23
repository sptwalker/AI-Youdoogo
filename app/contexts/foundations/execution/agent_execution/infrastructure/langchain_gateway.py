"""LangChain and current usage-gate adapters behind pure Agent ports."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import Any, cast

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, SystemMessage

from app.contexts.foundations.execution.agent_execution.contracts.execution import (
    AgentExecutionRequest,
    ExecutionError,
    LlmExecutionRequest,
    LlmExecutionResponse,
    LlmStreamChunk,
    TokenUsage,
)


def _message_text(message: AIMessage | AIMessageChunk) -> str:
    content = message.content
    return content if isinstance(content, str) else str(content)


class LangChainLlmExecutionAdapter:
    """Keep vendor message types outside the published execution contract."""

    def __init__(
        self,
        *,
        llm_factory: Callable[..., Any],
        usage_extractor: Callable[[Any], tuple[int, int, int]],
    ) -> None:
        self._llm_factory = llm_factory
        self._usage_extractor = usage_extractor

    async def invoke(self, request: LlmExecutionRequest) -> LlmExecutionResponse:
        llm = self._llm_factory(request.model_role, temperature=request.temperature)
        reply = await llm.ainvoke(
            [
                SystemMessage(content=request.system_prompt),
                HumanMessage(content=request.user_message),
            ]
        )
        prompt, completion, total = self._usage_extractor(reply)
        return LlmExecutionResponse(
            content=_message_text(reply),
            model=str(reply.response_metadata.get("model_name") or request.model_role),
            usage=TokenUsage(prompt, completion, total),
        )

    def stream(self, request: LlmExecutionRequest) -> AsyncIterator[LlmStreamChunk]:
        async def _iterate() -> AsyncIterator[LlmStreamChunk]:
            llm = self._llm_factory(request.model_role, temperature=request.temperature)
            full: AIMessageChunk | None = None
            async for chunk in llm.astream(
                [
                    SystemMessage(content=request.system_prompt),
                    HumanMessage(content=request.user_message),
                ]
            ):
                if not isinstance(chunk, AIMessageChunk):
                    continue
                full = chunk if full is None else cast(AIMessageChunk, full + chunk)
                prompt, completion, total = self._usage_extractor(full)
                yield LlmStreamChunk(
                    delta=_message_text(chunk),
                    accumulated_content=_message_text(full),
                    model=str(
                        full.response_metadata.get("model_name") or request.model_role
                    ),
                    usage=TokenUsage(prompt, completion, total),
                )

        return _iterate()


class CurrentUsageAuthorizationAdapter:
    """Translate the current daily budget gate into a pure decision."""

    def __init__(self, budget_exceeded: Callable[[], bool]) -> None:
        self._budget_exceeded = budget_exceeded

    def authorize(self, request: AgentExecutionRequest) -> ExecutionError | None:
        del request
        if not self._budget_exceeded():
            return None
        return ExecutionError(
            code="budget_exceeded",
            message="已达当日 LLM 用量预算上限，暂停调用（请联系管理员调整预算）",
        )
