"""SQLAlchemy mapper and repository for the existing desktop_message table."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.business.assistant_conversations.domain.models import ConversationMessage
from app.models.desktop import DesktopMessage


def message_to_domain(row: DesktopMessage) -> ConversationMessage:
    return ConversationMessage(
        id=row.id,
        owner_user_id=row.owner_user_id,
        speaker_type=row.speaker_type,
        speaker_agent_id=row.speaker_agent_id,
        speaker_name=row.speaker_name,
        content=row.content,
        create_time=row.create_time,
    )


class SQLAlchemyConversationRepository:
    """Conversation persistence whose mutation methods flush but never commit."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_recent(
        self, owner_user_id: uuid.UUID, *, limit: int
    ) -> list[ConversationMessage]:
        statement = (
            select(DesktopMessage)
            .where(DesktopMessage.owner_user_id == owner_user_id)
            .order_by(DesktopMessage.create_time.desc())
            .limit(limit)
        )
        rows = list((await self._session.execute(statement)).scalars())
        rows.reverse()
        return [message_to_domain(row) for row in rows]

    async def list_since(
        self, owner_user_id: uuid.UUID, *, since: datetime
    ) -> list[ConversationMessage]:
        statement = (
            select(DesktopMessage)
            .where(
                DesktopMessage.owner_user_id == owner_user_id,
                DesktopMessage.create_time >= since,
            )
            .order_by(DesktopMessage.create_time)
        )
        return [
            message_to_domain(row) for row in (await self._session.execute(statement)).scalars()
        ]

    async def list_before(
        self, owner_user_id: uuid.UUID, *, before: datetime
    ) -> list[ConversationMessage]:
        statement = (
            select(DesktopMessage)
            .where(
                DesktopMessage.owner_user_id == owner_user_id,
                DesktopMessage.create_time < before,
            )
            .order_by(DesktopMessage.create_time)
        )
        return [
            message_to_domain(row) for row in (await self._session.execute(statement)).scalars()
        ]

    async def add(self, message: ConversationMessage) -> None:
        self._session.add(
            DesktopMessage(
                id=message.id,
                owner_user_id=message.owner_user_id,
                speaker_type=message.speaker_type,
                speaker_agent_id=message.speaker_agent_id,
                speaker_name=message.speaker_name,
                content=message.content,
                create_time=message.create_time,
            )
        )
        await self._session.flush()

    async def delete(self, message_ids: tuple[uuid.UUID, ...]) -> None:
        if not message_ids:
            return
        await self._session.execute(
            delete(DesktopMessage).where(DesktopMessage.id.in_(message_ids))
        )
        await self._session.flush()
