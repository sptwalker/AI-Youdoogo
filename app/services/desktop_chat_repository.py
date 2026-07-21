"""Focused persistence helpers for desktop chat messages."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.desktop import DesktopMessage
from app.models.system import SysUser


def message_dict(message: DesktopMessage) -> dict[str, Any]:
    return {
        "id": str(message.id),
        "speaker_type": message.speaker_type,
        "speaker_agent_id": (
            str(message.speaker_agent_id) if message.speaker_agent_id else None
        ),
        "speaker_name": message.speaker_name,
        "content": message.content,
        "create_time": message.create_time.isoformat(),
    }


async def recent_window(
    db: AsyncSession, user: SysUser, *, limit: int
) -> list[DesktopMessage]:
    stmt = (
        select(DesktopMessage)
        .where(DesktopMessage.owner_user_id == user.id)
        .order_by(DesktopMessage.create_time.desc())
        .limit(limit)
    )
    return list(reversed(list((await db.execute(stmt)).scalars())))


async def save_message(
    db: AsyncSession,
    *,
    owner_user_id: uuid.UUID,
    speaker_type: str,
    speaker_name: str,
    content: str,
    speaker_agent_id: uuid.UUID | None = None,
) -> DesktopMessage:
    message = DesktopMessage(
        owner_user_id=owner_user_id,
        speaker_type=speaker_type,
        speaker_agent_id=speaker_agent_id,
        speaker_name=speaker_name,
        content=content,
    )
    db.add(message)
    await db.commit()
    await db.refresh(message)
    return message
