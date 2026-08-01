"""Remote Agent execution application：Module 2「远端拥有 _prepare」的并行应用（docs/23 §6.2）。

与本地 ``AgentExecutionApplication`` **同 execute/stream 面**，由组合根按 ``expert_execution_mode``
二选一（Branch-by-Abstraction，默认 local 逐字不变）。模块 1 缝在 ``LlmCompletionPort`` 无法承载
prepare 上下文（``expert_id``/``use_knowledge``/``knowledge_base_ids``/转发令牌）且 ``sources`` 需
回流，故这里把「缝」上移为一个并行远端应用，本地热路径**零改动**。

**本地留读、远端做算**：``knowledge_base_ids``（查库可见性）、``global_prompt``（sys_config）、
``term_prompt``（术语字典）在本地读 youdoo 库（真源），结果随体传远端；prompt 拼接 + 知识 Search
扇出在远端完成。释放 DB 事务（``release_before_external_call``）后再发远端调用。

兜底：远端在**首 delta 前**失败 → 委托本地兜底应用（同模块 1 ``FallbackCompletionPort`` 语义）；
回滚 = ``expert_execution_mode`` 归 local / canary 归 0。

# ponytail: authorize/boundary/record 编排与本地并行一份（约 30 行）；远端转正后再抽公共编排。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.execution.agent_execution.application.ports import (
    AgentExecutionRecorderPort,
    ExecutionClock,
    ExternalExecutionBoundaryPort,
    UsageAuthorizationPort,
)
from app.contexts.foundations.execution.agent_execution.application.prompts import (
    DEFAULT_GLOBAL_PROMPT,
)
from app.contexts.foundations.execution.agent_execution.application.use_cases import (
    AgentExecutionApplication,
    llm_role_for,
)
from app.contexts.foundations.execution.agent_execution.contracts.execution import (
    AgentExecutionRequest,
    AgentExecutionResult,
    AgentExecutionStatus,
    AgentExecutionStreamEvent,
    ExecutionError,
    SourceReference,
    TokenUsage,
)
from app.contexts.foundations.execution.agent_execution.infrastructure.remote_execution_adapter import (  # noqa: E501
    ExpertPlatformError,
)
from app.contexts.foundations.execution.agent_execution.infrastructure.remote_prepare_adapter import (  # noqa: E501
    RemoteExpertPrepareAdapter,
)
from app.contexts.foundations.governance.system_configuration.public import resolve_configuration
from app.contexts.foundations.knowledge.semantic_catalog.public import term_prompt
from app.contexts.foundations.knowledge.wiki_management.public import (
    agent_visible_knowledge_base_ids,
)
from app.core.internal_token import mint_internal_token
from app.platform.eventing.remote_step import GATEWAY_AUDIENCE, LLM_COMPLETE_SCOPE

logger = logging.getLogger(__name__)

_KNOWLEDGE_AUDIENCE = "ai-knowledge-service"


class RemoteAgentExecutionApplication:
    """Run one execution via the remote expert platform; fall back to local before first delta."""

    def __init__(
        self,
        *,
        session: AsyncSession,
        prepare: RemoteExpertPrepareAdapter,
        usage_authorization: UsageAuthorizationPort,
        recorder: AgentExecutionRecorderPort,
        clock: ExecutionClock,
        fallback: AgentExecutionApplication,
        external_boundary: ExternalExecutionBoundaryPort | None = None,
        forward_gateway_token: bool = False,
    ) -> None:
        self._session = session
        self._prepare = prepare
        self._usage_authorization = usage_authorization
        self._recorder = recorder
        self._clock = clock
        self._fallback = fallback
        self._external_boundary = external_boundary
        self._forward_gateway_token = forward_gateway_token

    async def _local_context(
        self, request: AgentExecutionRequest
    ) -> tuple[list[str] | None, str, str]:
        """本地读 youdoo 库（真源）：可见知识库 id + 全局提示 + 术语提示。随体传远端。"""
        expert = request.expert
        global_prompt = str(
            await resolve_configuration(self._session, "agent_global_prompt", DEFAULT_GLOBAL_PROMPT)
        )
        term = await term_prompt(self._session)
        knowledge_base_ids: list[str] | None = None
        if request.use_knowledge:
            ids = await agent_visible_knowledge_base_ids(
                self._session,
                department_id=expert.department_id,
                owner_agent_id=expert.expert_id,
            )
            knowledge_base_ids = [str(i) for i in ids]
        return knowledge_base_ids, global_prompt, term

    def _relay_token(self, request: AgentExecutionRequest) -> str | None:
        """转发令牌（aud=知识服务, scope=knowledge:search, actor=真人）；私钥只在本服务。"""
        if not request.use_knowledge:
            return None
        return mint_internal_token(
            service_id="ai-youdoogo",
            audience=_KNOWLEDGE_AUDIENCE,
            scope=("knowledge:search",),
            actor_id=str(request.user_id) if request.user_id else None,
        )

    def _gateway_token(self, request: AgentExecutionRequest) -> str | None:
        """转发令牌（aud=网关, scope=llm:complete）；门控关→None→远端回落 echo。私钥只在本服务。"""
        if not self._forward_gateway_token:
            return None
        return mint_internal_token(
            service_id="ai-youdoogo",
            audience=GATEWAY_AUDIENCE,
            scope=(LLM_COMPLETE_SCOPE,),
            actor_id=str(request.user_id) if request.user_id else None,
        )

    async def _create_remote(
        self, request: AgentExecutionRequest
    ) -> tuple[str, tuple[SourceReference, ...]]:
        """本地读 → authorize → 释放事务 → mint 转发令牌 → 远端 create。返回 (id, sources)。"""
        knowledge_base_ids, global_prompt, term = await self._local_context(request)
        denial = self._usage_authorization.authorize(request)
        if denial is not None:
            raise RuntimeError(denial.message)
        if self._external_boundary is not None:
            await self._external_boundary.release_before_external_call()
        return await self._prepare.create(
            str(request.expert.expert_id),
            model_role=llm_role_for(request.expert.model_role),
            user_message=request.user_message,
            use_knowledge=request.use_knowledge,
            knowledge_base_ids=knowledge_base_ids,
            knowledge_token=self._relay_token(request),
            gateway_token=self._gateway_token(request),
            global_prompt=global_prompt,
            term_prompt=term,
        )

    async def execute(self, request: AgentExecutionRequest) -> AgentExecutionResult:
        started = self._clock.monotonic_ms()
        try:
            execution_id, sources = await self._create_remote(request)
        except ExpertPlatformError:
            # 首 delta 前远端失败 → 委托本地兜底（本地自行 record，语义同 FallbackCompletionPort）。
            logger.warning("远端专家平台不可用，回退本地执行 expert=%s", request.expert.name)
            return await self._fallback.execute(request)
        content: str | None = None
        model: str | None = None
        usage = TokenUsage()
        error: ExecutionError | None = None
        try:
            async for chunk in self._prepare.stream(execution_id):
                content = chunk.accumulated_content
                model = chunk.model or model
                usage = chunk.usage if chunk.usage.total_tokens else usage
            status = AgentExecutionStatus.SUCCEEDED
        except Exception as exc:  # noqa: BLE001 - failure is an auditable result（已过首调，不再回退）
            logger.exception("远端专家执行流式失败 expert=%s", request.expert.name)
            status = AgentExecutionStatus.FAILED
            error = ExecutionError(code="execution_failed", message=str(exc))
        result = AgentExecutionResult(
            status=status,
            trace=request.trace,
            content=content,
            model=model,
            usage=usage,
            sources=sources,
            duration_ms=max(0, self._clock.monotonic_ms() - started),
            error=error,
        )
        return await self._recorder.record(request, result)

    async def stream(
        self, request: AgentExecutionRequest
    ) -> AsyncIterator[AgentExecutionStreamEvent]:
        started = self._clock.monotonic_ms()
        try:
            execution_id, sources = await self._create_remote(request)
        except ExpertPlatformError:
            logger.warning("远端专家平台不可用，回退本地流式 expert=%s", request.expert.name)
            async for event in self._fallback.stream(request):
                yield event
            return
        content: str | None = None
        model: str | None = None
        usage = TokenUsage()
        error: ExecutionError | None = None
        try:
            async for chunk in self._prepare.stream(execution_id):
                content = chunk.accumulated_content
                model = chunk.model or model
                usage = chunk.usage if chunk.usage.total_tokens else usage
                if chunk.delta:
                    yield AgentExecutionStreamEvent(delta=chunk.delta)
            status = AgentExecutionStatus.SUCCEEDED
        except Exception as exc:  # noqa: BLE001 - keep partial output and record failure
            logger.exception("远端专家执行流式失败 expert=%s", request.expert.name)
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
