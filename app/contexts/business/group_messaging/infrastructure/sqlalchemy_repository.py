"""SQLAlchemy mapper and repository for the existing discussion tables."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.business.group_messaging.domain.models import (
    MEMBER_HUMAN,
    Channel,
    MemberDraft,
    Message,
)
from app.models.discussion import ChannelMember, DiscussionChannel, DiscussionMessage


def channel_to_domain(row: DiscussionChannel) -> Channel:
    return Channel(
        id=row.id,
        name=row.name,
        department_id=row.department_id,
        default_agent_id=row.default_agent_id,
        creator_id=row.creator_id,
        is_archived=row.is_archived,
        is_deleted=row.is_delete,
        create_time=row.create_time,
    )


def message_to_domain(row: DiscussionMessage) -> Message:
    return Message(
        id=row.id,
        channel_id=row.channel_id,
        speaker_type=row.speaker_type,
        speaker_id=row.speaker_id,
        speaker_name=row.speaker_name,
        content=row.content,
        mentioned_agent_ids=tuple(str(value) for value in (row.mentioned_agent_ids or [])),
        ai_source_record_id=row.ai_source_record_id,
        ref_type=row.ref_type,
        ref_id=row.ref_id,
        attachments=tuple(
            dict(value) for value in (row.attachments or []) if isinstance(value, dict)
        ),
        create_time=row.create_time,
        is_deleted=row.is_delete,
    )


class SQLAlchemyGroupMessagingRepository:
    """Persistence adapter whose mutation methods flush but never commit."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._channels: dict[uuid.UUID, DiscussionChannel] = {}
        self._messages: dict[uuid.UUID, DiscussionMessage] = {}

    async def add_channel(self, channel: Channel) -> None:
        row = DiscussionChannel(
            id=channel.id,
            name=channel.name,
            department_id=channel.department_id,
            default_agent_id=channel.default_agent_id,
            creator_id=channel.creator_id,
            is_archived=channel.is_archived,
            is_delete=channel.is_deleted,
            create_time=channel.create_time,
        )
        self._session.add(row)
        await self._session.flush()
        self._channels[channel.id] = row

    async def get_channel(
        self, channel_id: uuid.UUID, *, include_deleted: bool = False
    ) -> Channel | None:
        row = await self._session.get(DiscussionChannel, channel_id)
        if row is None or (row.is_delete and not include_deleted):
            return None
        self._channels[channel_id] = row
        return channel_to_domain(row)

    async def save_channel(self, channel: Channel) -> None:
        row = self._channels.get(channel.id)
        if row is None:
            row = await self._session.get(DiscussionChannel, channel.id)
        if row is None:
            return
        row.name = channel.name
        row.department_id = channel.department_id
        row.default_agent_id = channel.default_agent_id
        row.creator_id = channel.creator_id
        row.is_archived = channel.is_archived
        row.is_delete = channel.is_deleted
        await self._session.flush()
        self._channels[channel.id] = row

    async def list_channels(self, *, department_id: uuid.UUID | None = None) -> list[Channel]:
        stmt = select(DiscussionChannel).where(DiscussionChannel.is_delete.is_(False))
        if department_id is not None:
            stmt = stmt.where(DiscussionChannel.department_id == department_id)
        stmt = stmt.order_by(DiscussionChannel.create_time)
        rows = list((await self._session.execute(stmt)).scalars())
        self._channels.update({row.id: row for row in rows})
        return [channel_to_domain(row) for row in rows]

    async def all_channel_ids(self) -> list[uuid.UUID]:
        stmt = select(DiscussionChannel.id).where(DiscussionChannel.is_delete.is_(False))
        return list((await self._session.execute(stmt)).scalars())

    async def add_members(self, channel_id: uuid.UUID, members: tuple[MemberDraft, ...]) -> int:
        added = 0
        for member in members:
            row = (
                await self._session.execute(
                    select(ChannelMember).where(
                        ChannelMember.channel_id == channel_id,
                        ChannelMember.member_type == member.member_type,
                        ChannelMember.member_id == member.member_id,
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                self._session.add(
                    ChannelMember(
                        channel_id=channel_id,
                        member_type=member.member_type,
                        member_id=member.member_id,
                        member_name=member.member_name,
                    )
                )
                added += 1
                continue
            if row.is_delete:
                row.is_delete = False
                row.member_name = member.member_name
                added += 1
        await self._session.flush()
        return added

    async def remove_member(
        self, channel_id: uuid.UUID, member_type: str, member_id: uuid.UUID
    ) -> None:
        row = (
            await self._session.execute(
                select(ChannelMember).where(
                    ChannelMember.channel_id == channel_id,
                    ChannelMember.member_type == member_type,
                    ChannelMember.member_id == member_id,
                    ChannelMember.is_delete.is_(False),
                )
            )
        ).scalar_one_or_none()
        if row is not None:
            row.is_delete = True
            await self._session.flush()

    async def deactivate_members(self, channel_id: uuid.UUID) -> None:
        rows = (
            await self._session.execute(
                select(ChannelMember).where(
                    ChannelMember.channel_id == channel_id,
                    ChannelMember.is_delete.is_(False),
                )
            )
        ).scalars()
        for row in rows:
            row.is_delete = True
        await self._session.flush()

    async def list_members(self, channel_id: uuid.UUID) -> list[MemberDraft]:
        stmt = select(ChannelMember).where(
            ChannelMember.channel_id == channel_id,
            ChannelMember.is_delete.is_(False),
        )
        return [
            MemberDraft(row.member_type, row.member_id, row.member_name)
            for row in (await self._session.execute(stmt)).scalars()
        ]

    async def channel_ids_for_user(self, user_id: uuid.UUID) -> list[uuid.UUID]:
        stmt = select(ChannelMember.channel_id).where(
            ChannelMember.member_type == MEMBER_HUMAN,
            ChannelMember.member_id == user_id,
            ChannelMember.is_delete.is_(False),
        )
        return list((await self._session.execute(stmt)).scalars())

    async def is_member(self, channel_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        stmt = select(ChannelMember.id).where(
            ChannelMember.channel_id == channel_id,
            ChannelMember.member_type == MEMBER_HUMAN,
            ChannelMember.member_id == user_id,
            ChannelMember.is_delete.is_(False),
        )
        return (await self._session.execute(stmt)).first() is not None

    async def mark_read(self, channel_id: uuid.UUID, user_id: uuid.UUID, read_at: datetime) -> None:
        row = (
            await self._session.execute(
                select(ChannelMember).where(
                    ChannelMember.channel_id == channel_id,
                    ChannelMember.member_type == MEMBER_HUMAN,
                    ChannelMember.member_id == user_id,
                    ChannelMember.is_delete.is_(False),
                )
            )
        ).scalar_one_or_none()
        if row is not None:
            row.last_read_at = read_at
            await self._session.flush()

    async def channels_with_unread(self, user_id: uuid.UUID) -> list[tuple[Channel, int]]:
        stmt = (
            select(ChannelMember, DiscussionChannel)
            .join(DiscussionChannel, DiscussionChannel.id == ChannelMember.channel_id)
            .where(
                ChannelMember.member_type == MEMBER_HUMAN,
                ChannelMember.member_id == user_id,
                ChannelMember.is_delete.is_(False),
                DiscussionChannel.is_delete.is_(False),
            )
            .order_by(DiscussionChannel.create_time.desc())
        )
        rows = (await self._session.execute(stmt)).all()
        result: list[tuple[Channel, int]] = []
        for member, channel_row in rows:
            conditions = [
                DiscussionMessage.channel_id == channel_row.id,
                DiscussionMessage.speaker_id != user_id,
            ]
            if member.last_read_at is not None:
                conditions.append(DiscussionMessage.create_time > member.last_read_at)
            unread = int(
                (
                    await self._session.execute(
                        select(func.count()).select_from(DiscussionMessage).where(*conditions)
                    )
                ).scalar_one()
            )
            self._channels[channel_row.id] = channel_row
            result.append((channel_to_domain(channel_row), unread))
        return result

    async def add_message(self, message: Message) -> None:
        row = DiscussionMessage(
            id=message.id,
            channel_id=message.channel_id,
            speaker_type=message.speaker_type,
            speaker_id=message.speaker_id,
            speaker_name=message.speaker_name,
            content=message.content,
            mentioned_agent_ids=list(message.mentioned_agent_ids),
            ai_source_record_id=message.ai_source_record_id,
            ref_type=message.ref_type,
            ref_id=message.ref_id,
            attachments=[dict(value) for value in message.attachments],
            create_time=message.create_time,
            is_delete=message.is_deleted,
        )
        self._session.add(row)
        await self._session.flush()
        self._messages[message.id] = row

    async def get_message(self, message_id: uuid.UUID) -> Message | None:
        row = await self._session.get(DiscussionMessage, message_id)
        if row is None or row.is_delete:
            return None
        self._messages[message_id] = row
        return message_to_domain(row)

    async def save_message(self, message: Message) -> None:
        row = self._messages.get(message.id)
        if row is None:
            row = await self._session.get(DiscussionMessage, message.id)
        if row is None:
            return
        row.content = message.content
        row.ref_type = message.ref_type
        row.ref_id = message.ref_id
        row.is_delete = message.is_deleted
        await self._session.flush()
        self._messages[message.id] = row

    async def list_messages(self, channel_id: uuid.UUID, *, limit: int) -> list[Message]:
        stmt = (
            select(DiscussionMessage)
            .where(DiscussionMessage.channel_id == channel_id)
            .order_by(DiscussionMessage.create_time.desc())
            .limit(limit)
        )
        rows = list((await self._session.execute(stmt)).scalars())
        rows.reverse()
        self._messages.update({row.id: row for row in rows})
        return [message_to_domain(row) for row in rows]

    async def attachment_visible_to_user(self, *, storage_path: str, user_id: uuid.UUID) -> bool:
        stmt = (
            select(DiscussionMessage.attachments)
            .join(DiscussionChannel, DiscussionChannel.id == DiscussionMessage.channel_id)
            .join(ChannelMember, ChannelMember.channel_id == DiscussionMessage.channel_id)
            .where(
                DiscussionMessage.is_delete.is_(False),
                DiscussionChannel.is_delete.is_(False),
                ChannelMember.member_type == MEMBER_HUMAN,
                ChannelMember.member_id == user_id,
                ChannelMember.is_delete.is_(False),
            )
        )
        attachment_groups = (await self._session.execute(stmt)).scalars()
        return any(
            isinstance(attachment, dict) and attachment.get("storage_path") == storage_path
            for attachments in attachment_groups
            for attachment in (attachments or [])
        )
