"""Transport-neutral request-scoped Assistant Conversations operations."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.business.assistant_conversations.application.contracts import (
    AgentResult,
    AssistantResult,
    AttachmentDownloadResult,
    MessageResult,
    OrchestrationResult,
    Principal,
    SendMessageCommand,
)
from app.contexts.business.assistant_conversations.application.ports import (
    AgentExecutionPort,
    AssistantDirectoryPort,
    AttachmentStoragePort,
    ConversationArchivePort,
)
from app.contexts.business.assistant_conversations.application.use_cases import (
    AssistantConversationsApplication,
)
from app.contexts.business.assistant_conversations.domain.models import Participant
from app.contexts.business.assistant_conversations.infrastructure.adapters import (
    AgentRunner,
    AgentStream,
)
from app.contexts.business.assistant_conversations.infrastructure.composition import (
    build_assistant_conversations_application,
)


def _application(
    session: AsyncSession,
    *,
    assistants: AssistantDirectoryPort | None = None,
    agents: AgentExecutionPort | None = None,
    archive_port: ConversationArchivePort | None = None,
    attachment_storage: AttachmentStoragePort | None = None,
    agent_stream: AgentStream | None = None,
    agent_runner: AgentRunner | None = None,
) -> AssistantConversationsApplication:
    return build_assistant_conversations_application(
        session,
        assistants=assistants,
        agents=agents,
        archive_port=archive_port,
        attachment_storage=attachment_storage,
        agent_stream=agent_stream,
        agent_runner=agent_runner,
    )


async def get_conversation(session: AsyncSession, principal: Principal) -> dict[str, Any]:
    result = await _application(session).get_conversation(principal)
    return result.as_dict()


async def get_or_create_assistant(
    session: AsyncSession,
    principal: Principal,
) -> AssistantResult:
    return await _application(session).get_or_create_assistant(principal)


async def list_messages(
    session: AsyncSession,
    principal: Principal,
    *,
    archive_port: ConversationArchivePort | None = None,
) -> tuple[MessageResult, ...]:
    return await _application(session, archive_port=archive_port).list_messages(principal)


async def list_addable_agents(session: AsyncSession) -> tuple[AgentResult, ...]:
    return await _application(session).list_addable_agents()


async def archive_old(
    session: AsyncSession,
    principal: Principal,
    *,
    days: int | None = None,
    archive_port: ConversationArchivePort | None = None,
) -> int:
    return await _application(session, archive_port=archive_port).archive_old(
        principal,
        days=days,
    )


async def upload_attachment(
    session: AsyncSession,
    *,
    name: str,
    content: bytes,
    content_type: str,
    attachment_storage: AttachmentStoragePort | None = None,
) -> dict[str, Any]:
    result = await _application(session, attachment_storage=attachment_storage).upload_attachment(
        name=name,
        content=content,
        content_type=content_type,
    )
    return result.as_dict()


async def download_attachment(
    session: AsyncSession,
    *,
    storage_path: str,
    name: str,
    user_id: uuid.UUID,
    attachment_storage: AttachmentStoragePort | None = None,
) -> AttachmentDownloadResult:
    return await _application(session, attachment_storage=attachment_storage).download_attachment(
        storage_path=storage_path,
        name=name,
        user_id=user_id,
    )


async def pin_message(
    session: AsyncSession,
    *,
    owner_user_id: uuid.UUID,
    message_id: uuid.UUID,
    pinned_by_user_id: uuid.UUID,
) -> dict[str, Any]:
    result = await _application(session).pin_message(
        owner_user_id=owner_user_id,
        message_id=message_id,
        pinned_by_user_id=pinned_by_user_id,
    )
    return result.as_dict()


async def unpin_message(
    session: AsyncSession,
    *,
    owner_user_id: uuid.UUID,
    message_id: uuid.UUID,
) -> dict[str, Any]:
    result = await _application(session).unpin_message(
        owner_user_id=owner_user_id,
        message_id=message_id,
    )
    return result.as_dict()


async def send_message_stream(
    session: AsyncSession,
    command: SendMessageCommand,
    *,
    assistants: AssistantDirectoryPort | None = None,
    agents: AgentExecutionPort | None = None,
    agent_stream: AgentStream | None = None,
    agent_runner: AgentRunner | None = None,
) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    application = _application(
        session,
        assistants=assistants,
        agents=agents,
        agent_stream=agent_stream,
        agent_runner=agent_runner,
    )
    async for event in application.send_message_stream(command):
        yield event.name, event.data


async def emit_orchestration(
    session: AsyncSession,
    *,
    principal_id: uuid.UUID,
    assistant_id: uuid.UUID,
    assistant_name: str,
    snapshot: dict[str, object],
) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    application = _application(session)
    async for event in application.emit_orchestration(
        principal_id=principal_id,
        assistant=Participant(assistant_id, assistant_name),
        orchestration=OrchestrationResult(snapshot),
    ):
        yield event.name, event.data
