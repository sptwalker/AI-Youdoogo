"""Conversation message persistence hidden behind application-level operations."""

from __future__ import annotations

import uuid
from datetime import datetime

from app.contexts.business.assistant_conversations.application.contracts import (
    MessageResult,
    ReplyPreviewResult,
)
from app.contexts.business.assistant_conversations.application.ports import (
    Clock,
    ConversationUnitOfWorkFactory,
    IdentifierPort,
)
from app.contexts.business.assistant_conversations.domain.models import (
    ConversationMessage,
    ReplyPreview,
)
from app.contexts.shared_kernel import ResourceNotFound

_MAX_REPLY_PREVIEW_CHARS = 120


class ConversationMessageStore:
    """Own message lookup, validation, construction, and transaction boundaries."""

    def __init__(
        self,
        *,
        uow_factory: ConversationUnitOfWorkFactory,
        clock: Clock,
        identifiers: IdentifierPort,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._identifiers = identifiers

    async def list_since(
        self, owner_user_id: uuid.UUID, *, since: datetime
    ) -> tuple[MessageResult, ...]:
        async with self._uow_factory() as uow:
            messages = await uow.messages.list_since(owner_user_id, since=since)
        return tuple(self.as_result(message) for message in messages)

    async def list_recent(self, owner_user_id: uuid.UUID, *, limit: int) -> list[tuple[str, str]]:
        async with self._uow_factory() as uow:
            recent = await uow.messages.list_recent(owner_user_id, limit=limit)
        return [(message.speaker_name, message.content) for message in recent]

    async def list_before(
        self, owner_user_id: uuid.UUID, *, before: datetime
    ) -> tuple[ConversationMessage, ...]:
        async with self._uow_factory() as uow:
            messages = await uow.messages.list_before(owner_user_id, before=before)
        return tuple(messages)

    async def delete(self, message_ids: tuple[uuid.UUID, ...]) -> None:
        async with self._uow_factory() as uow:
            await uow.messages.delete(message_ids)
            await uow.commit()

    async def require_owned(
        self, owner_user_id: uuid.UUID, message_id: uuid.UUID
    ) -> ConversationMessage:
        async with self._uow_factory() as uow:
            message = await uow.messages.get_owned_message(owner_user_id, message_id)
        if message is None:
            raise ResourceNotFound("消息不存在")
        return message

    async def reply_preview(
        self,
        owner_user_id: uuid.UUID,
        reply_to_message_id: uuid.UUID | None,
    ) -> ReplyPreview | None:
        if reply_to_message_id is None:
            return None
        message = await self.require_owned(owner_user_id, reply_to_message_id)
        compact = " ".join(message.content.split())
        content = (
            compact
            if len(compact) <= _MAX_REPLY_PREVIEW_CHARS
            else compact[: _MAX_REPLY_PREVIEW_CHARS - 1] + "…"
        )
        return ReplyPreview(
            id=message.id,
            speaker_name=message.speaker_name,
            content=content,
        )

    async def attachment_visible_to_user(
        self, *, storage_path: str, user_id: uuid.UUID
    ) -> bool:
        async with self._uow_factory() as uow:
            return await uow.messages.attachment_visible_to_user(
                storage_path=storage_path,
                user_id=user_id,
            )

    async def save_existing(self, message: ConversationMessage) -> MessageResult:
        async with self._uow_factory() as uow:
            await uow.messages.save(message)
            await uow.commit()
        return self.as_result(message)

    async def add(
        self,
        *,
        owner_user_id: uuid.UUID,
        speaker_type: str,
        speaker_name: str,
        content: str,
        speaker_agent_id: uuid.UUID | None = None,
        reply_to_message_id: uuid.UUID | None = None,
        reply_preview: ReplyPreview | None = None,
        attachments: tuple[dict[str, object], ...] = (),
        is_pinned: bool = False,
        pinned_at: datetime | None = None,
        pinned_by_user_id: uuid.UUID | None = None,
    ) -> MessageResult:
        message = ConversationMessage(
            id=self._identifiers.new_id(),
            owner_user_id=owner_user_id,
            speaker_type=speaker_type,
            speaker_agent_id=speaker_agent_id,
            speaker_name=speaker_name,
            content=content,
            create_time=self._clock.now(),
            reply_to_message_id=reply_to_message_id,
            reply_preview=reply_preview,
            attachments=tuple(dict(value) for value in attachments),
            is_pinned=is_pinned,
            pinned_at=pinned_at,
            pinned_by_user_id=pinned_by_user_id,
        )
        async with self._uow_factory() as uow:
            await uow.messages.add(message)
            await uow.commit()
        return self.as_result(message)

    @staticmethod
    def as_result(message: ConversationMessage) -> MessageResult:
        preview = message.reply_preview
        return MessageResult(
            id=message.id,
            speaker_type=message.speaker_type,
            speaker_agent_id=message.speaker_agent_id,
            speaker_name=message.speaker_name,
            content=message.content,
            create_time=message.create_time,
            reply_to_message_id=message.reply_to_message_id,
            reply_preview=(
                None
                if preview is None
                else ReplyPreviewResult(
                    id=preview.id,
                    speaker_name=preview.speaker_name,
                    content=preview.content,
                )
            ),
            attachments=message.attachments,
            is_pinned=message.is_pinned,
            pinned_at=message.pinned_at,
            pinned_by_user_id=message.pinned_by_user_id,
        )
