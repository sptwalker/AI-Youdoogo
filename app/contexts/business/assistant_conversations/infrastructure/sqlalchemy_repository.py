"""SQLAlchemy mapper and repository for the existing desktop_message table."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.business.assistant_conversations.domain.models import (
    ConversationMessage,
    ReplyPreview,
)
from app.models.desktop import DesktopMessage


def message_to_domain(row: DesktopMessage) -> ConversationMessage:
    reply_preview = None
    if row.reply_to_message_id and row.reply_preview_speaker_name and row.reply_preview_content:
        reply_preview = ReplyPreview(
            id=row.reply_to_message_id,
            speaker_name=row.reply_preview_speaker_name,
            content=row.reply_preview_content,
        )
    return ConversationMessage(
        id=row.id,
        owner_user_id=row.owner_user_id,
        speaker_type=row.speaker_type,
        speaker_agent_id=row.speaker_agent_id,
        speaker_name=row.speaker_name,
        content=row.content,
        create_time=row.create_time,
        reply_to_message_id=row.reply_to_message_id,
        reply_preview=reply_preview,
        attachments=tuple(
            dict(value) for value in (row.attachments or []) if isinstance(value, dict)
        ),
        is_pinned=row.is_pinned,
        pinned_at=row.pinned_at,
        pinned_by_user_id=row.pinned_by_user_id,
    )


class SQLAlchemyConversationRepository:
    """Conversation persistence whose mutation methods flush but never commit."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._messages: dict[uuid.UUID, DesktopMessage] = {}

    async def list_recent(
        self, owner_user_id: uuid.UUID, *, limit: int
    ) -> list[ConversationMessage]:
        statement = (
            select(DesktopMessage)
            .where(
                DesktopMessage.owner_user_id == owner_user_id,
                DesktopMessage.is_delete.is_(False),
            )
            .order_by(DesktopMessage.create_time.desc(), DesktopMessage.id.desc())
            .limit(limit)
        )
        rows = list((await self._session.execute(statement)).scalars())
        rows.reverse()
        self._messages.update({row.id: row for row in rows})
        return [message_to_domain(row) for row in rows]

    async def list_since(
        self, owner_user_id: uuid.UUID, *, since: datetime
    ) -> list[ConversationMessage]:
        statement = (
            select(DesktopMessage)
            .where(
                DesktopMessage.owner_user_id == owner_user_id,
                DesktopMessage.create_time >= since,
                DesktopMessage.is_delete.is_(False),
            )
            .order_by(DesktopMessage.create_time, DesktopMessage.id)
        )
        rows = list((await self._session.execute(statement)).scalars())
        self._messages.update({row.id: row for row in rows})
        return [message_to_domain(row) for row in rows]

    async def list_before(
        self, owner_user_id: uuid.UUID, *, before: datetime
    ) -> list[ConversationMessage]:
        statement = (
            select(DesktopMessage)
            .where(
                DesktopMessage.owner_user_id == owner_user_id,
                DesktopMessage.create_time < before,
                DesktopMessage.is_delete.is_(False),
            )
            .order_by(DesktopMessage.create_time, DesktopMessage.id)
        )
        rows = list((await self._session.execute(statement)).scalars())
        self._messages.update({row.id: row for row in rows})
        return [message_to_domain(row) for row in rows]

    async def get_owned_message(
        self, owner_user_id: uuid.UUID, message_id: uuid.UUID
    ) -> ConversationMessage | None:
        row = await self._session.get(DesktopMessage, message_id)
        if row is None or row.is_delete or row.owner_user_id != owner_user_id:
            return None
        self._messages[row.id] = row
        return message_to_domain(row)

    async def list_pinned(self, owner_user_id: uuid.UUID) -> list[ConversationMessage]:
        statement = (
            select(DesktopMessage)
            .where(
                DesktopMessage.owner_user_id == owner_user_id,
                DesktopMessage.is_pinned.is_(True),
                DesktopMessage.is_delete.is_(False),
            )
            .order_by(DesktopMessage.pinned_at.desc(), DesktopMessage.create_time.desc())
        )
        rows = list((await self._session.execute(statement)).scalars())
        self._messages.update({row.id: row for row in rows})
        return [message_to_domain(row) for row in rows]

    async def add(self, message: ConversationMessage) -> None:
        row = DesktopMessage(
            id=message.id,
            owner_user_id=message.owner_user_id,
            speaker_type=message.speaker_type,
            speaker_agent_id=message.speaker_agent_id,
            speaker_name=message.speaker_name,
            content=message.content,
            create_time=message.create_time,
            reply_to_message_id=message.reply_to_message_id,
            reply_preview_speaker_name=(
                message.reply_preview.speaker_name if message.reply_preview else None
            ),
            reply_preview_content=message.reply_preview.content if message.reply_preview else None,
            attachments=[dict(value) for value in message.attachments],
            is_pinned=message.is_pinned,
            pinned_at=message.pinned_at,
            pinned_by_user_id=message.pinned_by_user_id,
        )
        self._session.add(row)
        await self._session.flush()
        self._messages[message.id] = row

    async def save(self, message: ConversationMessage) -> None:
        row = self._messages.get(message.id)
        if row is None:
            row = await self._session.get(DesktopMessage, message.id)
        if row is None:
            return
        row.content = message.content
        row.reply_to_message_id = message.reply_to_message_id
        row.reply_preview_speaker_name = (
            message.reply_preview.speaker_name if message.reply_preview else None
        )
        row.reply_preview_content = (
            message.reply_preview.content if message.reply_preview else None
        )
        row.attachments = [dict(value) for value in message.attachments]
        row.is_pinned = message.is_pinned
        row.pinned_at = message.pinned_at
        row.pinned_by_user_id = message.pinned_by_user_id
        await self._session.flush()
        self._messages[message.id] = row

    async def delete(self, message_ids: tuple[uuid.UUID, ...]) -> None:
        if not message_ids:
            return
        await self._session.execute(
            delete(DesktopMessage).where(DesktopMessage.id.in_(message_ids))
        )
        await self._session.flush()

    async def attachment_visible_to_user(self, *, storage_path: str, user_id: uuid.UUID) -> bool:
        statement = select(DesktopMessage.attachments).where(
            DesktopMessage.owner_user_id == user_id,
            DesktopMessage.is_delete.is_(False),
        )
        attachment_groups = (await self._session.execute(statement)).scalars()
        return any(
            isinstance(attachment, dict) and attachment.get("storage_path") == storage_path
            for attachments in attachment_groups
            for attachment in (attachments or [])
        )
