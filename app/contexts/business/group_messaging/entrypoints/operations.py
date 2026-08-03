"""Request-scoped Group Messaging operations for HTTP and compatibility callers."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.contexts.business.group_messaging.application.contracts import (
    AttachmentDownloadResult,
    ChannelResult,
    CreateChannelCommand,
    MemberInput,
    PostMessageCommand,
    Principal,
    UploadAttachmentCommand,
)
from app.contexts.business.group_messaging.infrastructure.composition import (
    build_group_messaging_application,
)


def _members(values: list[dict[str, Any]] | None) -> tuple[MemberInput, ...]:
    result: list[MemberInput] = []
    for value in values or []:
        member_type = value.get("member_type")
        member_id = value.get("member_id")
        if member_type not in {"human", "ai"} or not member_id:
            continue
        result.append(
            MemberInput(
                member_type=str(member_type),
                member_id=(
                    member_id if isinstance(member_id, uuid.UUID) else uuid.UUID(str(member_id))
                ),
                member_name=str(value.get("member_name") or ""),
            )
        )
    return tuple(result)


def _isolated_session_factory(
    session: AsyncSession,
) -> async_sessionmaker[AsyncSession]:
    bind = session.bind
    if bind is None:
        raise RuntimeError("Streaming Group Messaging requires a bound database session")
    return async_sessionmaker(bind, expire_on_commit=False)


async def create_channel(
    session: AsyncSession,
    *,
    name: str,
    department_id: uuid.UUID | None = None,
    creator_id: uuid.UUID | None = None,
    creator_name: str = "",
    default_agent_id: uuid.UUID | None = None,
    members: list[dict[str, Any]] | None = None,
) -> ChannelResult:
    return await build_group_messaging_application(session).create_channel(
        CreateChannelCommand(
            name=name,
            department_id=department_id,
            creator_id=creator_id,
            creator_name=creator_name,
            default_agent_id=default_agent_id,
            members=_members(members),
        )
    )


async def get_channel(session: AsyncSession, channel_id: uuid.UUID) -> ChannelResult:
    return await build_group_messaging_application(session).get_channel(channel_id)


async def list_channels(
    session: AsyncSession,
    *,
    department_id: uuid.UUID | None = None,
    principal_id: uuid.UUID | None = None,
    principal_role: str = "member",
) -> list[dict[str, Any]]:
    principal = (
        Principal(id=principal_id, role_code=principal_role) if principal_id is not None else None
    )
    rows = await build_group_messaging_application(session).list_channels(
        principal=principal, department_id=department_id
    )
    return [row.as_dict() for row in rows]


async def all_channel_ids(session: AsyncSession) -> list[str]:
    return list(await build_group_messaging_application(session).all_channel_ids())


async def add_members(
    session: AsyncSession,
    channel_id: uuid.UUID,
    members: list[dict[str, Any]],
    *,
    owner_id: uuid.UUID | None = None,
) -> int:
    return await build_group_messaging_application(session).add_members(
        channel_id, _members(members), owner_id=owner_id
    )


async def remove_member(
    session: AsyncSession,
    channel_id: uuid.UUID,
    member_type: str,
    member_id: uuid.UUID,
    *,
    owner_id: uuid.UUID | None = None,
) -> None:
    await build_group_messaging_application(session).remove_member(
        channel_id,
        member_type,
        member_id,
        owner_id=owner_id,
    )


async def list_members(
    session: AsyncSession,
    channel_id: uuid.UUID,
    *,
    member_id: uuid.UUID | None = None,
) -> list[dict[str, str]]:
    rows = await build_group_messaging_application(session).list_members(
        channel_id, member_id=member_id
    )
    return [row.as_dict() for row in rows]


async def my_channel_ids(session: AsyncSession, user_id: uuid.UUID) -> list[str]:
    return list(await build_group_messaging_application(session).channel_ids_for_user(user_id))


async def is_member(session: AsyncSession, channel_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    return await build_group_messaging_application(session).is_member(channel_id, user_id)


async def is_owner(session: AsyncSession, channel_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    return await build_group_messaging_application(session).is_owner(channel_id, user_id)


async def ensure_member_access(
    session: AsyncSession, channel_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    await build_group_messaging_application(session).ensure_member_access(channel_id, user_id)


async def disband_channel(
    session: AsyncSession,
    channel_id: uuid.UUID,
    *,
    owner_id: uuid.UUID | None = None,
) -> None:
    await build_group_messaging_application(session).disband_channel(channel_id, owner_id=owner_id)


async def mark_read(session: AsyncSession, channel_id: uuid.UUID, user_id: uuid.UUID) -> None:
    await build_group_messaging_application(session).mark_read(channel_id, user_id)


async def my_channels_with_unread(
    session: AsyncSession, user_id: uuid.UUID
) -> list[dict[str, Any]]:
    rows = await build_group_messaging_application(session).channels_with_unread(user_id)
    return [row.as_dict() for row in rows]


async def archive_channel(session: AsyncSession, channel_id: uuid.UUID) -> ChannelResult:
    return await build_group_messaging_application(session).archive_channel(channel_id)


async def archive_disbanded_channel(session: AsyncSession, channel_id: uuid.UUID) -> None:
    await build_group_messaging_application(session).archive_disbanded_channel(channel_id)


async def list_messages(
    session: AsyncSession,
    channel_id: uuid.UUID,
    *,
    limit: int = 100,
    member_id: uuid.UUID | None = None,
) -> list[dict[str, Any]]:
    rows = await build_group_messaging_application(session).list_messages(
        channel_id, limit=limit, member_id=member_id
    )
    return [row.as_dict() for row in rows]


async def post_message_stream(
    session: AsyncSession,
    channel_id: uuid.UUID,
    *,
    speaker_id: uuid.UUID | None,
    speaker_name: str,
    content: str,
    mentioned_agent_ids: list[uuid.UUID],
    attachments: list[dict[str, Any]] | None = None,
    require_member_id: uuid.UUID | None = None,
) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    factory = _isolated_session_factory(session)
    async with factory() as stream_session:
        application = build_group_messaging_application(stream_session)
        async for event in application.post_message_stream(
            PostMessageCommand(
                channel_id=channel_id,
                speaker_id=speaker_id,
                speaker_name=speaker_name,
                content=content,
                mentioned_agent_ids=tuple(mentioned_agent_ids),
                attachments=tuple(dict(value) for value in (attachments or [])),
                require_member_id=require_member_id,
            )
        ):
            yield event.name, event.data


async def subscribe_user_messages(
    session: AsyncSession, user_id: uuid.UUID
) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    factory = _isolated_session_factory(session)
    async with factory() as stream_session:
        application = build_group_messaging_application(stream_session)
        async for event in application.subscribe_user_messages(user_id):
            yield event.name, event.data


async def upload_attachment(
    session: AsyncSession,
    *,
    name: str,
    content: bytes,
    content_type: str,
) -> dict[str, Any]:
    result = await build_group_messaging_application(session).upload_attachment(
        UploadAttachmentCommand(
            name=name,
            content=content,
            content_type=content_type,
        )
    )
    return result.as_dict()


async def download_attachment(
    session: AsyncSession,
    *,
    storage_path: str,
    name: str,
    user_id: uuid.UUID,
) -> AttachmentDownloadResult:
    return await build_group_messaging_application(session).download_attachment(
        storage_path=storage_path,
        name=name,
        user_id=user_id,
    )


async def promote_message(
    session: AsyncSession,
    message_id: uuid.UUID,
    *,
    target: str,
    creator_id: uuid.UUID,
) -> dict[str, str]:
    return await build_group_messaging_application(session).promote_message(
        message_id,
        target=target,
        creator_id=creator_id,
    )
