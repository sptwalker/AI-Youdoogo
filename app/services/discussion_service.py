"""One-way compatibility facade for the Group Messaging bounded context."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.business.group_messaging.application.contracts import (
    DISBAND_ARCHIVE_EVENT as _DISBAND_ARCHIVE_EVENT,
)
from app.contexts.business.group_messaging.application.contracts import (
    ChannelResult,
    archive_file_id,
)
from app.contexts.business.group_messaging.domain.models import (
    MAX_FANOUT as _MAX_FANOUT,
)
from app.contexts.business.group_messaging.domain.models import (
    deduplicate_mentions,
)
from app.contexts.business.group_messaging.entrypoints import operations
from app.core.sse import Event

DISBAND_ARCHIVE_EVENT = _DISBAND_ARCHIVE_EVENT
MAX_FANOUT = _MAX_FANOUT


def _dedup(ids: list[uuid.UUID]) -> list[uuid.UUID]:
    """Retain the legacy helper while delegating the guardrail to the Domain."""
    return list(deduplicate_mentions(tuple(ids)))


def _archive_file_id(channel_id: uuid.UUID) -> uuid.UUID:
    """Retain the deterministic legacy helper for worker and test compatibility."""
    return archive_file_id(channel_id)


async def get_channel(db: AsyncSession, channel_id: uuid.UUID) -> ChannelResult:
    return await operations.get_channel(db, channel_id)


async def create_channel(
    db: AsyncSession,
    *,
    name: str,
    department_id: uuid.UUID | None = None,
    creator_id: uuid.UUID | None = None,
    creator_name: str = "",
    default_agent_id: uuid.UUID | None = None,
    members: list[dict[str, Any]] | None = None,
) -> ChannelResult:
    return await operations.create_channel(
        db,
        name=name,
        department_id=department_id,
        creator_id=creator_id,
        creator_name=creator_name,
        default_agent_id=default_agent_id,
        members=members,
    )


async def list_channels(
    db: AsyncSession, *, department_id: uuid.UUID | None = None
) -> list[dict[str, Any]]:
    return await operations.list_channels(db, department_id=department_id)


async def all_channel_ids(db: AsyncSession) -> list[str]:
    return await operations.all_channel_ids(db)


async def add_members(
    db: AsyncSession, channel_id: uuid.UUID, members: list[dict[str, Any]]
) -> int:
    return await operations.add_members(db, channel_id, members)


async def remove_member(
    db: AsyncSession,
    channel_id: uuid.UUID,
    member_type: str,
    member_id: uuid.UUID,
) -> None:
    await operations.remove_member(db, channel_id, member_type, member_id)


async def list_members(db: AsyncSession, channel_id: uuid.UUID) -> list[dict[str, str]]:
    return await operations.list_members(db, channel_id)


async def my_channel_ids(db: AsyncSession, user_id: uuid.UUID) -> list[str]:
    return await operations.my_channel_ids(db, user_id)


async def is_member(db: AsyncSession, channel_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    return await operations.is_member(db, channel_id, user_id)


async def is_owner(db: AsyncSession, channel_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    return await operations.is_owner(db, channel_id, user_id)


async def disband_channel(db: AsyncSession, channel_id: uuid.UUID) -> None:
    await operations.disband_channel(db, channel_id)


async def archive_disbanded_channel(db: AsyncSession, channel_id: uuid.UUID) -> None:
    await operations.archive_disbanded_channel(db, channel_id)


async def mark_read(db: AsyncSession, channel_id: uuid.UUID, user_id: uuid.UUID) -> None:
    await operations.mark_read(db, channel_id, user_id)


async def my_channels_with_unread(db: AsyncSession, user_id: uuid.UUID) -> list[dict[str, Any]]:
    return await operations.my_channels_with_unread(db, user_id)


async def archive_channel(db: AsyncSession, channel_id: uuid.UUID) -> ChannelResult:
    return await operations.archive_channel(db, channel_id)


async def list_messages(
    db: AsyncSession, channel_id: uuid.UUID, *, limit: int = 100
) -> list[dict[str, Any]]:
    return await operations.list_messages(db, channel_id, limit=limit)


async def post_message_stream(
    db: AsyncSession,
    channel_id: uuid.UUID,
    *,
    speaker_id: uuid.UUID | None,
    speaker_name: str,
    content: str,
    mentioned_agent_ids: list[uuid.UUID],
    attachments: list[dict[str, Any]] | None = None,
) -> AsyncIterator[Event]:
    async for event in operations.post_message_stream(
        db,
        channel_id,
        speaker_id=speaker_id,
        speaker_name=speaker_name,
        content=content,
        mentioned_agent_ids=mentioned_agent_ids,
        attachments=attachments,
    ):
        yield event


async def promote_message(
    db: AsyncSession,
    message_id: uuid.UUID,
    *,
    target: str,
    creator_id: uuid.UUID,
) -> dict[str, str]:
    return await operations.promote_message(
        db,
        message_id,
        target=target,
        creator_id=creator_id,
    )
