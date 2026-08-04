"""Request-scoped composition for Assistant Conversations."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.business.assistant_conversations.application.ports import (
    AgentExecutionPort,
    AssistantDirectoryPort,
    AttachmentStoragePort,
    ConversationArchivePort,
)
from app.contexts.business.assistant_conversations.application.use_cases import (
    AssistantConversationsApplication,
)
from app.contexts.business.assistant_conversations.infrastructure.adapters import (
    AgentRunner,
    AgentStream,
    KnowledgeAttachmentStorageAdapter,
    LegacyAgentExecutionAdapter,
    PublishedConfigurationAdapter,
    PublishedConversationArchiveAdapter,
    PublishedOrchestrationAdapter,
    SQLAlchemyAssistantDirectoryAdapter,
)
from app.contexts.business.assistant_conversations.infrastructure.sqlalchemy_uow import (
    SQLAlchemyConversationUnitOfWork,
)
from app.contexts.foundations.execution.agent_execution.public import (
    run_agent_snapshot,
)
from app.platform.deterministic import SystemClock, UUIDIdentifier


def build_assistant_conversations_application(
    session: AsyncSession,
    *,
    assistants: AssistantDirectoryPort | None = None,
    agents: AgentExecutionPort | None = None,
    archive_port: ConversationArchivePort | None = None,
    attachment_storage: AttachmentStoragePort | None = None,
    agent_stream: AgentStream | None = None,
    agent_runner: AgentRunner | None = None,
) -> AssistantConversationsApplication:
    return AssistantConversationsApplication(
        uow_factory=lambda: SQLAlchemyConversationUnitOfWork(session),
        assistants=assistants or SQLAlchemyAssistantDirectoryAdapter(session),
        configuration=PublishedConfigurationAdapter(session),
        agents=agents
        or LegacyAgentExecutionAdapter(
            session,
            agent_stream=agent_stream,
            agent_runner=agent_runner or run_agent_snapshot,
        ),
        orchestration=PublishedOrchestrationAdapter(session),
        archive_port=archive_port or PublishedConversationArchiveAdapter(session),
        attachment_storage=attachment_storage or KnowledgeAttachmentStorageAdapter(),
        clock=SystemClock(),
        identifiers=UUIDIdentifier(),
    )
