"""Published request-scoped operation for Organization department channels."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.business.group_messaging.application.contracts import ChannelResult
from app.contexts.business.group_messaging.infrastructure.channel_creation import (
    build_department_channel_creator,
)


async def create_department_channel(
    session: AsyncSession, *, name: str, department_id: uuid.UUID
) -> ChannelResult:
    return await build_department_channel_creator(session).execute(
        name=name,
        department_id=department_id,
    )
