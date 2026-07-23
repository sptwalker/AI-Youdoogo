"""Application orchestration for one Agent execution."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from app.contexts.foundations.execution.agent_execution.application.ports import (
    AgentExecutionRecorderPort,
    ExecutionClock,
    ExternalExecutionBoundaryPort,
    KnowledgeAugmentationPort,
    LlmExecutionPort,
    PromptAssemblyPort,
    UsageAuthorizationPort,
)
from app.contexts.foundations.execution.agent_execution.contracts.execution import (
    AgentExecutionRequest,
    AgentExecutionResult,
    AgentExecutionStatus,
    AgentExecutionStreamEvent,
    ExecutionError,
    LlmExecutionRequest,
    SourceReference,
    TokenUsage,
)

logger = logging.getLogger(__name__)

_LLM_ROLE_BY_TIER = {"daily": "default", "reasoning": "meeting_expert"}


def llm_role_for(model_role: str) -> str:
    """Translate the persisted expert tier to the stable LLM gateway role."""
    return _LLM_ROLE_BY_TIER.get(model_role, "default")


class AgentExecutionApplication:
    """Run external work through ports and always record a normalized outcome."""

    def __init__(
        self,
        *,
        prompt_port: PromptAssemblyPort,
        knowledge_port: KnowledgeAugmentationPort,
        usage_authorization: UsageAuthorizationPort,
        llm_port: LlmExecutionPort,
        recorder: AgentExecutionRecorderPort,
        clock: ExecutionClock,
        external_boundary: ExternalExecutionBoundaryPort | None = None,
    ) -> None:
        self._prompt = prompt_port
        self._knowledge = knowledge_port
        self._usage_authorization = usage_authorization
        self._llm = llm_port
        self._recorder = recorder
        self._clock = clock
        self._external_boundary = external_boundary

    async def execute(self, request: AgentExecutionRequest) -> AgentExecutionResult:
        started = self._clock.monotonic_ms()
        sources: tuple[SourceReference, ...] = ()
        try:
            llm_request, sources = await self._prepare(request)
            denial = self._usage_authorization.authorize(request)
            if denial is not None:
                raise RuntimeError(denial.message)
            if self._external_boundary is not None:
                await self._external_boundary.release_before_external_call()
            response = await self._llm.invoke(llm_request)
            result = AgentExecutionResult(
                status=AgentExecutionStatus.SUCCEEDED,
                trace=request.trace,
                content=response.content,
                model=response.model,
                usage=response.usage,
                sources=sources,
                duration_ms=max(0, self._clock.monotonic_ms() - started),
            )
        except Exception as exc:  # noqa: BLE001 - failure is an auditable result
            logger.exception(
                "Agent execution failed expert=%s task=%s",
                request.expert.name,
                request.task_type,
            )
            result = AgentExecutionResult(
                status=AgentExecutionStatus.FAILED,
                trace=request.trace,
                sources=sources,
                duration_ms=max(0, self._clock.monotonic_ms() - started),
                error=ExecutionError(code="execution_failed", message=str(exc)),
            )
        return await self._recorder.record(request, result)

    async def stream(
        self, request: AgentExecutionRequest
    ) -> AsyncIterator[AgentExecutionStreamEvent]:
        started = self._clock.monotonic_ms()
        sources: tuple[SourceReference, ...] = ()
        content: str | None = None
        model: str | None = None
        usage = TokenUsage()
        error: ExecutionError | None = None
        try:
            llm_request, sources = await self._prepare(request)
            denial = self._usage_authorization.authorize(request)
            if denial is not None:
                raise RuntimeError(denial.message)
            if self._external_boundary is not None:
                await self._external_boundary.release_before_external_call()
            async for chunk in self._llm.stream(llm_request):
                content = chunk.accumulated_content
                model = chunk.model or model
                usage = chunk.usage if chunk.usage.total_tokens else usage
                if chunk.delta:
                    yield AgentExecutionStreamEvent(delta=chunk.delta)
            status = AgentExecutionStatus.SUCCEEDED
        except Exception as exc:  # noqa: BLE001 - keep partial output and record failure
            logger.exception(
                "Streaming Agent execution failed expert=%s task=%s",
                request.expert.name,
                request.task_type,
            )
            status = AgentExecutionStatus.FAILED
            error = ExecutionError(code="execution_failed", message=str(exc))
        result = await self._recorder.record(
            request,
            AgentExecutionResult(
                status=status,
                trace=request.trace,
                content=content,
                model=model,
                usage=usage,
                sources=sources,
                duration_ms=max(0, self._clock.monotonic_ms() - started),
                error=error,
            ),
        )
        yield AgentExecutionStreamEvent(result=result)

    async def _prepare(
        self, request: AgentExecutionRequest
    ) -> tuple[LlmExecutionRequest, tuple[SourceReference, ...]]:
        system_prompt = await self._prompt.build(request.expert)
        message = request.user_message
        sources: tuple[SourceReference, ...] = ()
        if request.use_knowledge:
            augmentation = await self._knowledge.augment(request.expert, message)
            message = augmentation.message
            sources = augmentation.sources
        return (
            LlmExecutionRequest(
                model_role=llm_role_for(request.expert.model_role),
                system_prompt=system_prompt,
                user_message=message,
            ),
            sources,
        )
