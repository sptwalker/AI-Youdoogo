"""Request-scoped Agent Execution composition."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.execution.agent_execution.application.consult import (
    ConsultExpert,
)
from app.contexts.foundations.execution.agent_execution.application.record_queries import (
    AgentExecutionRecords,
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
    LangChainLlmExecutionAdapter,
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
from app.llm import get_llm_for_role
from app.llm.usage import budget_exceeded, extract_usage, record_usage


def build_agent_execution_application(session: AsyncSession) -> AgentExecutionApplication:
    return AgentExecutionApplication(
        prompt_port=CurrentPromptAssemblyAdapter(session),
        knowledge_port=CurrentKnowledgeAugmentationAdapter(session),
        usage_authorization=CurrentUsageAuthorizationAdapter(budget_exceeded),
        llm_port=LangChainLlmExecutionAdapter(
            llm_factory=get_llm_for_role,
            usage_extractor=extract_usage,
        ),
        recorder=SQLAlchemyAgentExecutionRecorder(session, None, record_usage),
        clock=SystemExecutionClock(),
        external_boundary=SQLAlchemyExternalExecutionBoundary(session),
    )


def build_consult_expert(session: AsyncSession) -> ConsultExpert:
    return ConsultExpert(
        experts=expert_snapshot_adapter.PublishedExpertSnapshotAdapter(session),
        executions=build_agent_execution_application(session),
    )


def build_agent_execution_records(session: AsyncSession) -> AgentExecutionRecords:
    return AgentExecutionRecords(SQLAlchemyAgentExecutionRecordQuery(session))
