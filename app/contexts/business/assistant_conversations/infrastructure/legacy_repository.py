"""Compatibility helpers backed by the canonical conversation repository/UoW."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.business.assistant_conversations.application.contracts import MessageResult
from app.contexts.business.assistant_conversations.domain.models import ConversationMessage
from app.contexts.business.assistant_conversations.infrastructure.sqlalchemy_repository import (
    SQLAlchemyConversationRepository,
)
from app.contexts.business.assistant_conversations.infrastructure.sqlalchemy_uow import (
    SQLAlchemyConversationUnitOfWork,
)
from app.models.desktop import DesktopMessage
from app.models.system import SysUser


def message_dict(message: ConversationMessage | DesktopMessage) -> dict[str, Any]:
    return MessageResult(
        id=message.id,
        speaker_type=message.speaker_type,
        speaker_agent_id=message.speaker_agent_id,
        speaker_name=message.speaker_name,
        content=message.content,
        create_time=message.create_time,
    ).as_dict()


async def recent_window(
    session: AsyncSession,
    user: SysUser,
    *,
    limit: int,
) -> list[ConversationMessage]:
    return await SQLAlchemyConversationRepository(session).list_recent(user.id, limit=limit)


async def save_message(
    session: AsyncSession,
    *,
    owner_user_id: uuid.UUID,
    speaker_type: str,
    speaker_name: str,
    content: str,
    speaker_agent_id: uuid.UUID | None = None,
) -> ConversationMessage:
    message = ConversationMessage(
        id=uuid.uuid4(),
        owner_user_id=owner_user_id,
        speaker_type=speaker_type,
        speaker_agent_id=speaker_agent_id,
        speaker_name=speaker_name,
        content=content,
        create_time=datetime.now(UTC),
    )
    async with SQLAlchemyConversationUnitOfWork(session) as uow:
        await uow.messages.add(message)
        await uow.commit()
    return message
