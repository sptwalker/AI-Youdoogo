"""Caller-owned ports for Assistant Conversations."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable
from datetime import datetime
from typing import Protocol, Self

from app.contexts.business.assistant_conversations.application.contracts import (
    AgentExecutionEvent,
    AgentExecutionRequest,
    ArchiveConversationRequest,
    OrchestrationResult,
    Principal,
)
from app.contexts.business.assistant_conversations.domain.models import (
    Assistant,
    ConversationMessage,
    Participant,
)


class ConversationRepository(Protocol):
    async def list_recent(
        self, owner_user_id: uuid.UUID, *, limit: int
    ) -> list[ConversationMessage]: ...

    async def list_since(
        self, owner_user_id: uuid.UUID, *, since: datetime
    ) -> list[ConversationMessage]: ...

    async def list_before(
        self, owner_user_id: uuid.UUID, *, before: datetime
    ) -> list[ConversationMessage]: ...

    async def add(self, message: ConversationMessage) -> None: ...

    async def delete(self, message_ids: tuple[uuid.UUID, ...]) -> None: ...


class ConversationUnitOfWork(Protocol):
    @property
    def messages(self) -> ConversationRepository: ...

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object | None,
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


ConversationUnitOfWorkFactory = Callable[[], ConversationUnitOfWork]


class AssistantDirectoryPort(Protocol):
    async def get_or_create(self, principal: Principal) -> Assistant: ...

    async def list_addable(self) -> tuple[Participant, ...]: ...

    async def resolve_addable(
        self, agent_ids: tuple[uuid.UUID, ...]
    ) -> tuple[Participant, ...]: ...


class ConfigurationPort(Protocol):
    async def integer(self, key: str, default: int) -> int: ...


class AgentExecutionPort(Protocol):
    def stream(self, request: AgentExecutionRequest) -> AsyncIterator[AgentExecutionEvent]: ...


class OrchestrationPort(Protocol):
    async def try_start(
        self,
        *,
        principal_id: uuid.UUID,
        assistant_id: uuid.UUID,
        message: str,
    ) -> OrchestrationResult | None: ...


class ConversationArchivePort(Protocol):
    async def archive(self, request: ArchiveConversationRequest) -> None: ...


class Clock(Protocol):
    def now(self) -> datetime: ...


class IdentifierPort(Protocol):
    def new_id(self) -> uuid.UUID: ...
