"""Group Messaging owned persistence, transaction, and integration ports."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable
from datetime import datetime
from typing import Protocol, Self

from app.contexts.business.group_messaging.application.contracts import (
    AgentReplyRequest,
    AgentReplyStreamEvent,
    ArchiveRequest,
    MessageStreamEvent,
    PromotionRequest,
)
from app.contexts.business.group_messaging.domain.models import (
    Channel,
    MemberDraft,
    Message,
)


class GroupMessagingRepository(Protocol):
    async def add_channel(self, channel: Channel) -> None: ...

    async def get_channel(
        self, channel_id: uuid.UUID, *, include_deleted: bool = False
    ) -> Channel | None: ...

    async def save_channel(self, channel: Channel) -> None: ...

    async def list_channels(self, *, department_id: uuid.UUID | None = None) -> list[Channel]: ...

    async def all_channel_ids(self) -> list[uuid.UUID]: ...

    async def add_members(self, channel_id: uuid.UUID, members: tuple[MemberDraft, ...]) -> int: ...

    async def remove_member(
        self, channel_id: uuid.UUID, member_type: str, member_id: uuid.UUID
    ) -> None: ...

    async def deactivate_members(self, channel_id: uuid.UUID) -> None: ...

    async def list_members(self, channel_id: uuid.UUID) -> list[MemberDraft]: ...

    async def channel_ids_for_user(self, user_id: uuid.UUID) -> list[uuid.UUID]: ...

    async def is_member(self, channel_id: uuid.UUID, user_id: uuid.UUID) -> bool: ...

    async def mark_read(
        self, channel_id: uuid.UUID, user_id: uuid.UUID, read_at: datetime
    ) -> None: ...

    async def channels_with_unread(self, user_id: uuid.UUID) -> list[tuple[Channel, int]]: ...

    async def add_message(self, message: Message) -> None: ...

    async def get_message(self, message_id: uuid.UUID) -> Message | None: ...

    async def save_message(self, message: Message) -> None: ...

    async def list_messages(self, channel_id: uuid.UUID, *, limit: int) -> list[Message]: ...

    async def attachment_visible_to_user(
        self, *, storage_path: str, user_id: uuid.UUID
    ) -> bool: ...


class GroupMessagingUnitOfWork(Protocol):
    @property
    def messages(self) -> GroupMessagingRepository: ...

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object | None,
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


GroupMessagingUnitOfWorkFactory = Callable[[], GroupMessagingUnitOfWork]


class RealtimeDeliveryPort(Protocol):
    async def publish(
        self, channel_id: uuid.UUID, event_name: str, data: dict[str, object]
    ) -> None: ...


class RealtimeSubscriptionPort(Protocol):
    def subscribe_user(
        self, *, user_id: uuid.UUID, channel_ids: tuple[uuid.UUID, ...]
    ) -> AsyncIterator[MessageStreamEvent]: ...


class AgentReplyPort(Protocol):
    def stream(self, request: AgentReplyRequest) -> AsyncIterator[AgentReplyStreamEvent]: ...


class AttachmentStoragePort(Protocol):
    async def put(self, *, object_name: str, content: bytes, content_type: str) -> str: ...

    async def get(self, *, object_name: str) -> bytes: ...


class ConversationArchivePort(Protocol):
    async def archive(self, request: ArchiveRequest) -> None: ...


class PromotionPort(Protocol):
    async def promote(self, request: PromotionRequest) -> uuid.UUID: ...


class OutboxPort(Protocol):
    async def enqueue_disband_archive(self, channel_id: uuid.UUID) -> None: ...


class Clock(Protocol):
    def now(self) -> datetime: ...


class IdentifierPort(Protocol):
    def new_id(self) -> uuid.UUID: ...

    def new_object_token(self) -> str: ...
