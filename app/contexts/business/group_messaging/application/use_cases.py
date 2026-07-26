"""Group Messaging use cases and transaction ownership."""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator

from app.contexts.business.group_messaging.application.contracts import (
    MAX_ATTACHMENT_BYTES,
    AgentReplyRequest,
    AgentReplyStreamEvent,
    ArchiveRequest,
    AttachmentDownloadResult,
    AttachmentResult,
    ChannelResult,
    CreateChannelCommand,
    MemberInput,
    MemberResult,
    MessageResult,
    MessageStreamEvent,
    PostMessageCommand,
    Principal,
    PromotionRequest,
    UploadAttachmentCommand,
    archive_file_id,
)
from app.contexts.business.group_messaging.application.ports import (
    AgentReplyPort,
    AttachmentStoragePort,
    Clock,
    ConversationArchivePort,
    GroupMessagingRepository,
    GroupMessagingUnitOfWorkFactory,
    IdentifierPort,
    OutboxPort,
    PromotionPort,
    RealtimeDeliveryPort,
    RealtimeSubscriptionPort,
)
from app.contexts.business.group_messaging.domain.models import (
    MEMBER_HUMAN,
    SPEAKER_AI,
    SPEAKER_HUMAN,
    Channel,
    MemberDraft,
    Message,
    deduplicate_mentions,
)
from app.contexts.shared_kernel import (
    InvalidInput,
    PermissionDenied,
    ResourceNotFound,
    RuleViolation,
)

_CONTEXT_N = 20
_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")
logger = logging.getLogger(__name__)


def _channel_result(channel: Channel, *, unread: int | None = None) -> ChannelResult:
    return ChannelResult(
        id=channel.id,
        name=channel.name,
        department_id=channel.department_id,
        default_agent_id=channel.default_agent_id,
        creator_id=channel.creator_id,
        is_archived=channel.is_archived,
        create_time=channel.create_time,
        unread=unread,
    )


def _message_result(message: Message) -> MessageResult:
    return MessageResult(
        id=message.id,
        channel_id=message.channel_id,
        speaker_type=message.speaker_type,
        speaker_id=message.speaker_id,
        speaker_name=message.speaker_name,
        content=message.content,
        mentioned_agent_ids=message.mentioned_agent_ids,
        ai_source_record_id=message.ai_source_record_id,
        ref_type=message.ref_type,
        ref_id=message.ref_id,
        attachments=message.attachments,
        create_time=message.create_time,
    )


class GroupMessagingApplication:
    """Deep application boundary for membership, messages, delivery, and archive."""

    def __init__(
        self,
        *,
        uow_factory: GroupMessagingUnitOfWorkFactory,
        realtime_delivery: RealtimeDeliveryPort,
        realtime_subscription: RealtimeSubscriptionPort,
        agent_replies: AgentReplyPort,
        attachment_storage: AttachmentStoragePort,
        archive_port: ConversationArchivePort,
        promotion_port: PromotionPort,
        outbox_port: OutboxPort,
        clock: Clock,
        identifiers: IdentifierPort,
    ) -> None:
        self._uow_factory = uow_factory
        self._realtime_delivery = realtime_delivery
        self._realtime_subscription = realtime_subscription
        self._agent_replies = agent_replies
        self._attachment_storage = attachment_storage
        self._archive_port = archive_port
        self._promotion_port = promotion_port
        self._outbox_port = outbox_port
        self._clock = clock
        self._identifiers = identifiers

    async def create_channel(self, command: CreateChannelCommand) -> ChannelResult:
        channel = Channel(
            id=self._identifiers.new_id(),
            name=command.name,
            department_id=command.department_id,
            default_agent_id=command.default_agent_id,
            creator_id=command.creator_id,
            create_time=self._clock.now(),
        )
        members = [
            MemberDraft(value.member_type, value.member_id, value.member_name)
            for value in command.members
        ]
        if command.creator_id is not None:
            members.append(MemberDraft(MEMBER_HUMAN, command.creator_id, command.creator_name))
        async with self._uow_factory() as uow:
            await uow.messages.add_channel(channel)
            if members:
                await uow.messages.add_members(channel.id, tuple(members))
            await uow.commit()
        return _channel_result(channel)

    async def get_channel(self, channel_id: uuid.UUID) -> ChannelResult:
        async with self._uow_factory() as uow:
            channel = await self._get_required(uow.messages, channel_id)
        return _channel_result(channel)

    async def list_channels(
        self,
        *,
        principal: Principal | None = None,
        department_id: uuid.UUID | None = None,
    ) -> tuple[ChannelResult, ...]:
        async with self._uow_factory() as uow:
            channels = await uow.messages.list_channels(department_id=department_id)
            if principal is not None and not principal.is_manager:
                visible_ids = set(await uow.messages.channel_ids_for_user(principal.id))
                channels = [channel for channel in channels if channel.id in visible_ids]
        return tuple(_channel_result(channel) for channel in channels)

    async def all_channel_ids(self) -> tuple[str, ...]:
        async with self._uow_factory() as uow:
            ids = await uow.messages.all_channel_ids()
        return tuple(str(channel_id) for channel_id in ids)

    async def add_members(
        self,
        channel_id: uuid.UUID,
        members: tuple[MemberInput, ...],
        *,
        owner_id: uuid.UUID | None = None,
    ) -> int:
        drafts = tuple(
            MemberDraft(value.member_type, value.member_id, value.member_name)
            for value in members
            if value.member_type in {"human", "ai"}
        )
        async with self._uow_factory() as uow:
            channel = await self._get_required(uow.messages, channel_id)
            if owner_id is not None:
                self._require_owner(channel, owner_id, "仅群主可添加成员")
            added = await uow.messages.add_members(channel_id, drafts)
            await uow.commit()
        return added

    async def remove_member(
        self,
        channel_id: uuid.UUID,
        member_type: str,
        member_id: uuid.UUID,
        *,
        owner_id: uuid.UUID | None = None,
    ) -> None:
        async with self._uow_factory() as uow:
            channel = await self._get_required(uow.messages, channel_id)
            if owner_id is not None:
                self._require_owner(channel, owner_id, "仅群主可踢出成员")
            channel.ensure_owner_is_not_removed(member_type=member_type, member_id=member_id)
            await uow.messages.remove_member(channel_id, member_type, member_id)
            await uow.commit()

    async def list_members(
        self, channel_id: uuid.UUID, *, member_id: uuid.UUID | None = None
    ) -> tuple[MemberResult, ...]:
        async with self._uow_factory() as uow:
            await self._get_required(uow.messages, channel_id)
            if member_id is not None:
                await self._require_member(uow.messages, channel_id, member_id)
            members = await uow.messages.list_members(channel_id)
        return tuple(
            MemberResult(value.member_type, value.member_id, value.member_name) for value in members
        )

    async def channel_ids_for_user(self, user_id: uuid.UUID) -> tuple[str, ...]:
        async with self._uow_factory() as uow:
            ids = await uow.messages.channel_ids_for_user(user_id)
        return tuple(str(channel_id) for channel_id in ids)

    async def is_member(self, channel_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        async with self._uow_factory() as uow:
            return await uow.messages.is_member(channel_id, user_id)

    async def is_owner(self, channel_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        async with self._uow_factory() as uow:
            channel = await self._get_required(uow.messages, channel_id)
        return channel.is_owner(user_id)

    async def ensure_member_access(self, channel_id: uuid.UUID, user_id: uuid.UUID) -> None:
        async with self._uow_factory() as uow:
            await self._get_required(uow.messages, channel_id)
            await self._require_member(uow.messages, channel_id, user_id)

    async def disband_channel(
        self, channel_id: uuid.UUID, *, owner_id: uuid.UUID | None = None
    ) -> None:
        async with self._uow_factory() as uow:
            channel = await self._get_required(uow.messages, channel_id)
            if owner_id is not None:
                self._require_owner(channel, owner_id, "仅群主可解散讨论群")
            channel.disband()
            await uow.messages.deactivate_members(channel_id)
            await uow.messages.save_channel(channel)
            await self._outbox_port.enqueue_disband_archive(channel_id)
            await uow.commit()

    async def mark_read(self, channel_id: uuid.UUID, user_id: uuid.UUID) -> None:
        async with self._uow_factory() as uow:
            await self._get_required(uow.messages, channel_id)
            await self._require_member(uow.messages, channel_id, user_id)
            await uow.messages.mark_read(channel_id, user_id, self._clock.now())
            await uow.commit()

    async def channels_with_unread(self, user_id: uuid.UUID) -> tuple[ChannelResult, ...]:
        async with self._uow_factory() as uow:
            rows = await uow.messages.channels_with_unread(user_id)
        return tuple(_channel_result(channel, unread=unread) for channel, unread in rows)

    async def archive_channel(self, channel_id: uuid.UUID) -> ChannelResult:
        async with self._uow_factory() as uow:
            channel = await self._get_required(uow.messages, channel_id)
            channel.archive()
            await uow.messages.save_channel(channel)
            await uow.commit()
        await self._archive(channel, strict=False)
        return _channel_result(channel)

    async def archive_disbanded_channel(self, channel_id: uuid.UUID) -> None:
        async with self._uow_factory() as uow:
            channel = await self._get_required(uow.messages, channel_id, include_deleted=True)
        await self._archive(channel, strict=True)

    async def list_messages(
        self,
        channel_id: uuid.UUID,
        *,
        limit: int = 100,
        member_id: uuid.UUID | None = None,
    ) -> tuple[MessageResult, ...]:
        async with self._uow_factory() as uow:
            await self._get_required(uow.messages, channel_id)
            if member_id is not None:
                await self._require_member(uow.messages, channel_id, member_id)
            messages = await uow.messages.list_messages(channel_id, limit=limit)
        return tuple(_message_result(message) for message in messages)

    async def post_message_stream(
        self, command: PostMessageCommand
    ) -> AsyncIterator[MessageStreamEvent]:
        channel, human = await self._save_human_message(command)
        human_result = _message_result(human)
        human_data = human_result.as_dict()
        yield MessageStreamEvent.message_persisted(human_result)
        await self._realtime_delivery.publish(command.channel_id, "message", human_data)

        targets = deduplicate_mentions(command.mentioned_agent_ids)
        recent_context = await self._recent_context(command.channel_id, targets=targets)
        for agent_id in targets:
            async for event in self._stream_agent_reply(
                command,
                agent_id=agent_id,
                channel_name=channel.name,
                recent_context=recent_context,
            ):
                yield event

    async def _save_human_message(self, command: PostMessageCommand) -> tuple[Channel, Message]:
        async with self._uow_factory() as uow:
            channel = await self._get_required(uow.messages, command.channel_id)
            if command.require_member_id is not None:
                await self._require_member(
                    uow.messages, command.channel_id, command.require_member_id
                )
            channel.ensure_postable()
            human = Message(
                id=self._identifiers.new_id(),
                channel_id=command.channel_id,
                speaker_type=SPEAKER_HUMAN,
                speaker_id=command.speaker_id,
                speaker_name=command.speaker_name,
                content=command.content,
                mentioned_agent_ids=tuple(str(value) for value in command.mentioned_agent_ids),
                attachments=tuple(dict(value) for value in command.attachments),
                create_time=self._clock.now(),
            )
            await uow.messages.add_message(human)
            await uow.commit()
        return channel, human

    async def _recent_context(
        self,
        channel_id: uuid.UUID,
        *,
        targets: tuple[uuid.UUID, ...],
    ) -> str:
        if not targets:
            return "（暂无发言）"
        history = await self.list_messages(channel_id, limit=_CONTEXT_N)
        transcript = "\n".join(f"{item.speaker_name}：{item.content}" for item in history)
        return transcript or "（暂无发言）"

    async def _stream_agent_reply(
        self,
        command: PostMessageCommand,
        *,
        agent_id: uuid.UUID,
        channel_name: str,
        recent_context: str,
    ) -> AsyncIterator[MessageStreamEvent]:
        request = AgentReplyRequest(
            agent_id=agent_id,
            user_id=command.speaker_id,
            channel_name=channel_name,
            content=command.content,
            recent_context=recent_context,
        )
        async for reply_event in self._agent_replies.stream(request):
            transient = self._transient_reply_event(reply_event)
            if transient is not None:
                yield transient
                continue
            if reply_event.name != "complete" or reply_event.speaker_agent_id is None:
                continue
            ai_message = await self._save_ai_message(command.channel_id, reply_event)
            ai_result = _message_result(ai_message)
            ai_data = ai_result.as_dict()
            yield MessageStreamEvent.message_persisted(ai_result)
            if reply_event.publish_realtime:
                await self._realtime_delivery.publish(command.channel_id, "message", ai_data)

    @staticmethod
    def _transient_reply_event(
        reply_event: AgentReplyStreamEvent,
    ) -> MessageStreamEvent | None:
        if reply_event.name == "start":
            return MessageStreamEvent.turn_started(
                speaker_agent_id=reply_event.speaker_agent_id,
                speaker_name=reply_event.speaker_name,
            )
        if reply_event.name == "delta":
            return MessageStreamEvent.delta(reply_event.text)
        return None

    async def _save_ai_message(
        self,
        channel_id: uuid.UUID,
        reply_event: AgentReplyStreamEvent,
    ) -> Message:
        if reply_event.speaker_agent_id is None:
            raise RuntimeError("Completed Agent reply has no speaker id")
        message = Message(
            id=self._identifiers.new_id(),
            channel_id=channel_id,
            speaker_type=SPEAKER_AI,
            speaker_id=reply_event.speaker_agent_id,
            speaker_name=reply_event.speaker_name,
            content=reply_event.content,
            ai_source_record_id=reply_event.source_record_id,
            create_time=self._clock.now(),
        )
        async with self._uow_factory() as uow:
            await uow.messages.add_message(message)
            await uow.commit()
        return message

    async def subscribe_user_messages(
        self, user_id: uuid.UUID
    ) -> AsyncIterator[MessageStreamEvent]:
        async with self._uow_factory() as uow:
            channel_ids = tuple(await uow.messages.channel_ids_for_user(user_id))
        async for event in self._realtime_subscription.subscribe_user(
            user_id=user_id, channel_ids=channel_ids
        ):
            yield event

    async def upload_attachment(self, command: UploadAttachmentCommand) -> AttachmentResult:
        if len(command.content) > MAX_ATTACHMENT_BYTES:
            raise RuleViolation(f"文件过大（>{MAX_ATTACHMENT_BYTES // 1024 // 1024}MB）")
        name = command.name or "未命名"
        object_name = f"chat/{self._identifiers.new_object_token()}/{name}"
        storage_path = await self._attachment_storage.put(
            object_name=object_name,
            content=command.content,
            content_type=command.content_type or "application/octet-stream",
        )
        return AttachmentResult(
            attachment_type=("image" if name.lower().endswith(_IMAGE_EXTENSIONS) else "file"),
            name=name,
            storage_path=storage_path,
            size=len(command.content),
        )

    async def download_attachment(
        self, *, storage_path: str, name: str, user_id: uuid.UUID
    ) -> AttachmentDownloadResult:
        _, _, object_name = storage_path.partition("/")
        if not object_name.startswith("chat/"):
            raise InvalidInput("非法附件路径")
        async with self._uow_factory() as uow:
            visible = await uow.messages.attachment_visible_to_user(
                storage_path=storage_path, user_id=user_id
            )
        if not visible:
            raise PermissionDenied("无权访问该附件")
        content = await self._attachment_storage.get(object_name=object_name)
        return AttachmentDownloadResult(name=name, content=content)

    async def promote_message(
        self,
        message_id: uuid.UUID,
        *,
        target: str,
        creator_id: uuid.UUID,
    ) -> dict[str, str]:
        async with self._uow_factory() as uow:
            message = await uow.messages.get_message(message_id)
        if message is None or message.is_deleted:
            raise ResourceNotFound("消息不存在")
        message.assert_promotable(target)
        ref_id = await self._promotion_port.promote(
            PromotionRequest(
                target=target,
                title=message.content[:60] or "讨论升格",
                content=message.content,
                creator_id=creator_id,
                source_message_id=message.id,
            )
        )
        message.record_promotion(target=target, ref_id=ref_id)
        async with self._uow_factory() as uow:
            await uow.messages.save_message(message)
            await uow.commit()
        return {"ref_type": target, "ref_id": str(ref_id)}

    async def _archive(self, channel: Channel, *, strict: bool) -> None:
        if channel.creator_id is None:
            return
        async with self._uow_factory() as uow:
            messages = await uow.messages.list_messages(channel.id, limit=500)
        if not messages:
            return
        transcript = "\n".join(f"{message.speaker_name}：{message.content}" for message in messages)
        request = ArchiveRequest(
            channel_id=channel.id,
            channel_name=channel.name,
            creator_id=channel.creator_id,
            transcript=transcript,
            file_id=archive_file_id(channel.id),
        )
        try:
            await self._archive_port.archive(request)
        except Exception:
            if strict:
                raise
            logger.warning("群聊归档入库失败 channel=%s", channel.id, exc_info=True)

    @staticmethod
    async def _get_required(
        repository: GroupMessagingRepository,
        channel_id: uuid.UUID,
        *,
        include_deleted: bool = False,
    ) -> Channel:
        channel = await repository.get_channel(channel_id, include_deleted=include_deleted)
        if channel is None:
            raise ResourceNotFound("讨论频道不存在")
        return channel

    @staticmethod
    async def _require_member(
        repository: GroupMessagingRepository,
        channel_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> None:
        if not await repository.is_member(channel_id, user_id):
            raise PermissionDenied("仅群成员可访问")

    @staticmethod
    def _require_owner(channel: Channel, user_id: uuid.UUID, message: str) -> None:
        if not channel.is_owner(user_id):
            raise PermissionDenied(message)
