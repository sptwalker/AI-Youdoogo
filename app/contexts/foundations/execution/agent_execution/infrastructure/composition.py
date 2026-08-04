"""Request-scoped Agent Execution composition."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.execution.agent_execution.application.consult import (
    ConsultExpert,
)
from app.contexts.foundations.execution.agent_execution.application.ports import (
    AgentExecutionPort,
    AgentExecutionRecorderPort,
    AgentExecutionRecordQueryPort,
    ExecutionClock,
    ExternalExecutionBoundaryPort,
    KnowledgeAugmentationPort,
    PromptAssemblyPort,
    UsageAuthorizationPort,
)
from app.contexts.foundations.execution.agent_execution.application.use_cases import (
    AgentExecutionApplication,
)
from app.contexts.foundations.execution.agent_execution.infrastructure import (
    expert_snapshot_adapter,
)
from app.contexts.foundations.execution.agent_execution.infrastructure.current_adapters import (
    CurrentKnowledgeAugmentationAdapter,
    CurrentPromptAssemblyAdapter,
)
from app.contexts.foundations.execution.agent_execution.infrastructure.langchain_gateway import (
    CurrentUsageAuthorizationAdapter,
)
from app.contexts.foundations.execution.agent_execution.infrastructure.remote_application import (
    RemoteAgentExecutionApplication,
)
from app.contexts.foundations.execution.agent_execution.infrastructure.remote_prepare_adapter import (  # noqa: E501
    RemoteExpertPrepareAdapter,
)
from app.contexts.foundations.execution.agent_execution.infrastructure.sqlalchemy_recorder import (
    SQLAlchemyAgentExecutionRecorder,
)
from app.contexts.foundations.execution.agent_execution.infrastructure.sqlalchemy_records import (
    SQLAlchemyAgentExecutionRecordQuery,
)
from app.contexts.foundations.execution.agent_execution.infrastructure.system_clock import (
    SystemExecutionClock,
)
from app.contexts.foundations.execution.agent_execution.infrastructure.transaction_boundary import (
    SQLAlchemyExternalExecutionBoundary,
)
from app.contexts.foundations.governance.usage_budget.public import (
    budget_exceeded,
    record_usage,
)
from app.contexts.foundations.model_gateway.public import (
    _route_remote,
    build_llm_completion_port,
)
from app.core.config import get_settings


def select_agent_execution(
    session: AsyncSession,
    *,
    prompt_port: PromptAssemblyPort,
    knowledge_port: KnowledgeAugmentationPort,
    usage_authorization: UsageAuthorizationPort,
    recorder: AgentExecutionRecorderPort,
    clock: ExecutionClock,
    external_boundary: ExternalExecutionBoundaryPort | None = None,
) -> AgentExecutionPort:
    """按 ``expert_execution_mode`` + 单次 canary 抽样二选一（Branch-by-Abstraction）。

    命中（唯一一次 ``_route_remote`` 抽样）→ Module 2 ``RemoteAgentExecutionApplication``
    （远端拥有 prepare），本地兜底 llm_port 走 ``build_llm_completion_port``。未命中 / mode=local
    → 本地 ``AgentExecutionApplication``，llm_port 同样走 ``build_llm_completion_port``（它只按
    正交的 LLM 网关 canary 定 Local/Remote，不再二次抽 expert canary——否则远端曝光叠成约 2 倍）。
    """
    settings = get_settings()
    if (
        settings.expert_execution_mode == "remote"
        and settings.expert_platform_url
        and _route_remote(settings.expert_platform_canary_percent)
    ):
        fallback = AgentExecutionApplication(
            prompt_port=prompt_port,
            knowledge_port=knowledge_port,
            usage_authorization=usage_authorization,
            llm_port=build_llm_completion_port(),
            recorder=recorder,
            clock=clock,
            external_boundary=external_boundary,
        )
        return RemoteAgentExecutionApplication(
            session=session,
            prepare=RemoteExpertPrepareAdapter(base_url=settings.expert_platform_url),
            usage_authorization=usage_authorization,
            recorder=recorder,
            clock=clock,
            external_boundary=external_boundary,
            fallback=fallback,
            forward_gateway_token=settings.expert_forward_gateway_token,
        )
    return AgentExecutionApplication(
        prompt_port=prompt_port,
        knowledge_port=knowledge_port,
        usage_authorization=usage_authorization,
        # 未命中/本地：纯本地 llm_port，不再二次抽 expert canary（见函数 docstring）。
        llm_port=build_llm_completion_port(),
        recorder=recorder,
        clock=clock,
        external_boundary=external_boundary,
    )


def build_agent_execution_application(
    session: AsyncSession,
    *,
    release_before_external_call: bool = True,
) -> AgentExecutionPort:
    return select_agent_execution(
        session,
        prompt_port=CurrentPromptAssemblyAdapter(session),
        knowledge_port=CurrentKnowledgeAugmentationAdapter(session),
        usage_authorization=CurrentUsageAuthorizationAdapter(budget_exceeded),
        recorder=SQLAlchemyAgentExecutionRecorder(session, None, record_usage),
        clock=SystemExecutionClock(),
        external_boundary=(
            SQLAlchemyExternalExecutionBoundary(session)
            if release_before_external_call
            else None
        ),
    )


def build_consult_expert(session: AsyncSession) -> ConsultExpert:
    return ConsultExpert(
        experts=expert_snapshot_adapter.PublishedExpertSnapshotAdapter(session),
        executions=build_agent_execution_application(session),
    )


def build_agent_execution_records(
    session: AsyncSession,
) -> AgentExecutionRecordQueryPort:
    return SQLAlchemyAgentExecutionRecordQuery(session)
