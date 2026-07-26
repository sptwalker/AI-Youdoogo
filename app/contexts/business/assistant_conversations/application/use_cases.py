"""Assistant Conversations use cases and transaction ownership."""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timedelta

from app.contexts.business.assistant_conversations.application.contracts import (
    AgentExecutionRequest,
    AgentResult,
    ArchiveConversationRequest,
    AssistantResult,
    AttachmentDownloadResult,
    AttachmentResult,
    ConsultedReply,
    ConversationResult,
    ConversationStreamEvent,
    MessageResult,
    OrchestrationResult,
    Principal,
    ReplyPreviewResult,
    SendMessageCommand,
)
from app.contexts.business.assistant_conversations.application.ports import (
    AgentExecutionPort,
    AssistantDirectoryPort,
    AttachmentStoragePort,
    Clock,
    ConfigurationPort,
    ConversationArchivePort,
    ConversationUnitOfWorkFactory,
    IdentifierPort,
    OrchestrationPort,
)
from app.contexts.business.assistant_conversations.domain.models import (
    SPEAKER_AI,
    SPEAKER_USER,
    Assistant,
    ConversationMessage,
    Participant,
    ReplyPreview,
    deduplicate_added_agents,
    describe_user_turn,
    direct_chat_prompt,
    ensure_added_agent_limit,
    progress_text,
    round_count,
    roundtable_prompt,
)
from app.contexts.shared_kernel import (
    InvalidInput,
    PermissionDenied,
    ResourceNotFound,
    RuleViolation,
)

_DEFAULT_HISTORY_DAYS = 10
_MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024
_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")
_MAX_REPLY_PREVIEW_CHARS = 120

logger = logging.getLogger(__name__)


def _assistant_result(assistant: Assistant) -> AssistantResult:
    return AssistantResult(
        id=assistant.id,
        owner_user_id=assistant.owner_user_id,
        name=assistant.name,
    )


def _agent_result(agent: Participant) -> AgentResult:
    return AgentResult(id=agent.id, name=agent.name, title=agent.title)


def _reply_preview_result(preview: ReplyPreview | None) -> ReplyPreviewResult | None:
    if preview is None:
        return None
    return ReplyPreviewResult(
        id=preview.id,
        speaker_name=preview.speaker_name,
        content=preview.content,
    )


def _message_result(message: ConversationMessage) -> MessageResult:
    return MessageResult(
        id=message.id,
        speaker_type=message.speaker_type,
        speaker_agent_id=message.speaker_agent_id,
        speaker_name=message.speaker_name,
        content=message.content,
        create_time=message.create_time,
        reply_to_message_id=message.reply_to_message_id,
        reply_preview=_reply_preview_result(message.reply_preview),
        attachments=message.attachments,
        is_pinned=message.is_pinned,
        pinned_at=message.pinned_at,
        pinned_by_user_id=message.pinned_by_user_id,
    )


class AssistantConversationsApplication:
    """Own conversation lifecycle, persistence, and stream ordering."""

    def __init__(
        self,
        *,
        uow_factory: ConversationUnitOfWorkFactory,
        assistants: AssistantDirectoryPort,
        configuration: ConfigurationPort,
        agents: AgentExecutionPort,
        orchestration: OrchestrationPort,
        archive_port: ConversationArchivePort,
        attachment_storage: AttachmentStoragePort,
        clock: Clock,
        identifiers: IdentifierPort,
    ) -> None:
        self._uow_factory = uow_factory
        self._assistants = assistants
        self._configuration = configuration
        self._agents = agents
        self._orchestration = orchestration
        self._archive_port = archive_port
        self._attachment_storage = attachment_storage
        self._clock = clock
        self._identifiers = identifiers

    async def get_or_create_assistant(self, principal: Principal) -> AssistantResult:
        return _assistant_result(await self._assistants.get_or_create(principal))

    async def list_addable_agents(self) -> tuple[AgentResult, ...]:
        return tuple(_agent_result(agent) for agent in await self._assistants.list_addable())

    async def get_conversation(self, principal: Principal) -> ConversationResult:
        assistant = await self._assistants.get_or_create(principal)
        days = await self._history_days()
        await self._archive_old(principal, days=days, assistant=assistant)
        async with self._uow_factory() as uow:
            messages = await uow.messages.list_since(
                principal.id,
                since=self._clock.now() - timedelta(days=days),
            )
        addable = await self._assistants.list_addable()
        return ConversationResult(
            assistant=_assistant_result(assistant),
            messages=tuple(_message_result(message) for message in messages),
            addable_agents=tuple(_agent_result(agent) for agent in addable),
        )

    async def list_messages(self, principal: Principal) -> tuple[MessageResult, ...]:
        days = await self._history_days()
        await self._archive_old(principal, days=days)
        async with self._uow_factory() as uow:
            messages = await uow.messages.list_since(
                principal.id,
                since=self._clock.now() - timedelta(days=days),
            )
        return tuple(_message_result(message) for message in messages)

    async def archive_old(self, principal: Principal, *, days: int | None = None) -> int:
        retention_days = days if days is not None else await self._history_days()
        return await self._archive_old(principal, days=retention_days)

    async def upload_attachment(
        self,
        *,
        name: str,
        content: bytes,
        content_type: str,
    ) -> AttachmentResult:
        if len(content) > _MAX_ATTACHMENT_BYTES:
            raise RuleViolation(f"文件过大（>{_MAX_ATTACHMENT_BYTES // 1024 // 1024}MB）")
        safe_name = name or "未命名"
        object_name = f"desktop-chat/{self._identifiers.new_object_token()}/{safe_name}"
        storage_path = await self._attachment_storage.put(
            object_name=object_name,
            content=content,
            content_type=content_type or "application/octet-stream",
        )
        return AttachmentResult(
            attachment_type=("image" if safe_name.lower().endswith(_IMAGE_EXTENSIONS) else "file"),
            name=safe_name,
            storage_path=storage_path,
            size=len(content),
        )

    async def download_attachment(
        self,
        *,
        storage_path: str,
        name: str,
        user_id: uuid.UUID,
    ) -> AttachmentDownloadResult:
        _, _, object_name = storage_path.partition("/")
        if not object_name.startswith("desktop-chat/"):
            raise InvalidInput("非法附件路径")
        async with self._uow_factory() as uow:
            visible = await uow.messages.attachment_visible_to_user(
                storage_path=storage_path,
                user_id=user_id,
            )
        if not visible:
            raise PermissionDenied("无权访问该附件")
        content = await self._attachment_storage.get(object_name=object_name)
        return AttachmentDownloadResult(name=name, content=content)

    async def pin_message(
        self,
        *,
        owner_user_id: uuid.UUID,
        message_id: uuid.UUID,
        pinned_by_user_id: uuid.UUID,
    ) -> MessageResult:
        message = await self._require_owned_message(owner_user_id, message_id)
        if message.is_pinned:
            return _message_result(message)
        updated = ConversationMessage(
            id=message.id,
            owner_user_id=message.owner_user_id,
            speaker_type=message.speaker_type,
            speaker_agent_id=message.speaker_agent_id,
            speaker_name=message.speaker_name,
            content=message.content,
            create_time=message.create_time,
            reply_to_message_id=message.reply_to_message_id,
            reply_preview=message.reply_preview,
            attachments=message.attachments,
            is_pinned=True,
            pinned_at=self._clock.now(),
            pinned_by_user_id=pinned_by_user_id,
        )
        async with self._uow_factory() as uow:
            await uow.messages.save(updated)
            await uow.commit()
        return _message_result(updated)

    async def unpin_message(
        self,
        *,
        owner_user_id: uuid.UUID,
        message_id: uuid.UUID,
    ) -> MessageResult:
        message = await self._require_owned_message(owner_user_id, message_id)
        if not message.is_pinned:
            return _message_result(message)
        updated = ConversationMessage(
            id=message.id,
            owner_user_id=message.owner_user_id,
            speaker_type=message.speaker_type,
            speaker_agent_id=message.speaker_agent_id,
            speaker_name=message.speaker_name,
            content=message.content,
            create_time=message.create_time,
            reply_to_message_id=message.reply_to_message_id,
            reply_preview=message.reply_preview,
            attachments=message.attachments,
            is_pinned=False,
            pinned_at=None,
            pinned_by_user_id=None,
        )
        async with self._uow_factory() as uow:
            await uow.messages.save(updated)
            await uow.commit()
        return _message_result(updated)

    async def _archive_old(
        self,
        principal: Principal,
        *,
        days: int,
        assistant: Assistant | None = None,
    ) -> int:
        async with self._uow_factory() as uow:
            old = await uow.messages.list_before(
                principal.id,
                before=self._clock.now() - timedelta(days=days),
            )
        if not old:
            return 0
        assistant = assistant or await self._assistants.get_or_create(principal)
        if assistant.personal_knowledge_base_id is None:
            return 0
        raw_transcript = "\n".join(f"{message.speaker_name}：{message.content}" for message in old)
        span = f"{old[0].create_time:%Y-%m-%d} ~ {old[-1].create_time:%Y-%m-%d}"
        try:
            await self._archive_port.archive(
                ArchiveConversationRequest(
                    principal_id=principal.id,
                    knowledge_base_id=assistant.personal_knowledge_base_id,
                    title_template=f"{principal.display_name}对话{{title_suffix}} {span}",
                    transcript=raw_transcript,
                )
            )
        except Exception:  # noqa: BLE001 - preserve retry-on-next-load behavior
            logger.warning(
                "对话归档入库失败 user=%s，保留消息下次重试",
                principal.id,
                exc_info=True,
            )
            return 0
        message_ids = tuple(message.id for message in old)
        async with self._uow_factory() as uow:
            await uow.messages.delete(message_ids)
            await uow.commit()
        return len(message_ids)

    async def send_message_stream(
        self, command: SendMessageCommand
    ) -> AsyncIterator[ConversationStreamEvent]:
        principal = command.principal
        participants = await self._resolve_participants(command)
        rounds = await self._rounds(command, participant_count=len(participants))
        conversation = await self._recent_conversation(command)
        reply_preview = await self._resolve_reply_preview(principal.id, command.reply_to_message_id)

        user_message = await self._save_message(
            owner_user_id=principal.id,
            speaker_type=SPEAKER_USER,
            speaker_name=principal.display_name,
            content=command.message,
            reply_to_message_id=command.reply_to_message_id,
            reply_preview=reply_preview,
            attachments=command.attachments,
        )
        model_turn = describe_user_turn(command.message, command.attachments)
        conversation.append((principal.display_name, model_turn))
        yield ConversationStreamEvent.message_persisted(_message_result(user_message))

        orchestration = await self._try_start_orchestration(command, participants)
        if orchestration is not None:
            async for stream_event in self.emit_orchestration(
                principal_id=principal.id,
                assistant=participants[0],
                orchestration=orchestration,
            ):
                yield stream_event
            return

        async for stream_event in self._emit_roundtable(
            command=command,
            participants=participants,
            rounds=rounds,
            conversation=conversation,
        ):
            yield stream_event

    async def _resolve_participants(self, command: SendMessageCommand) -> tuple[Participant, ...]:
        ensure_added_agent_limit(command.add_agent_ids, max_add=command.max_add)
        assistant = await self._assistants.get_or_create(command.principal)
        added_ids = deduplicate_added_agents(
            command.add_agent_ids,
            assistant_id=assistant.id,
            max_add=command.max_add,
        )
        added = await self._assistants.resolve_addable(added_ids)
        return (Participant(assistant.id, assistant.name), *added)

    async def _rounds(self, command: SendMessageCommand, *, participant_count: int) -> int:
        configured = await self._configuration.integer(
            "desktop_roundtable_rounds", command.default_rounds
        )
        return round_count(
            configured,
            participant_count=participant_count,
            maximum=command.max_rounds,
        )

    async def _recent_conversation(self, command: SendMessageCommand) -> list[tuple[str, str]]:
        async with self._uow_factory() as uow:
            recent = await uow.messages.list_recent(
                command.principal.id,
                limit=command.recent_context,
            )
        return [(message.speaker_name, message.content) for message in recent]

    async def _try_start_orchestration(
        self,
        command: SendMessageCommand,
        participants: tuple[Participant, ...],
    ) -> OrchestrationResult | None:
        if len(participants) != 1 or command.attachments:
            return None
        return await self._orchestration.try_start(
            principal_id=command.principal.id,
            assistant_id=participants[0].id,
            message=command.message,
        )

    async def _emit_roundtable(
        self,
        *,
        command: SendMessageCommand,
        participants: tuple[Participant, ...],
        rounds: int,
        conversation: list[tuple[str, str]],
    ) -> AsyncIterator[ConversationStreamEvent]:
        for _round in range(rounds):
            for participant in participants:
                async for stream_event in self._emit_participant_turn(
                    command=command,
                    participant=participant,
                    participants=participants,
                    conversation=conversation,
                ):
                    yield stream_event

    async def _emit_participant_turn(
        self,
        *,
        command: SendMessageCommand,
        participant: Participant,
        participants: tuple[Participant, ...],
        conversation: list[tuple[str, str]],
    ) -> AsyncIterator[ConversationStreamEvent]:
        if len(participants) == 1:
            prompt = direct_chat_prompt(participant, tuple(conversation))
        else:
            prompt = roundtable_prompt(participant, participants, tuple(conversation))
        yield ConversationStreamEvent.turn_started(
            speaker_agent_id=participant.id,
            speaker_name=participant.name,
        )
        completed = None
        async for agent_event in self._agents.stream(
            AgentExecutionRequest(
                participant_id=participant.id,
                principal_id=command.principal.id,
                original_message=command.message,
                prompt=prompt,
            )
        ):
            if agent_event.name == "delta":
                yield ConversationStreamEvent.delta(agent_event.text)
            elif agent_event.name == "complete":
                completed = agent_event
        if completed is None:
            raise RuntimeError("Agent reply completed without an execution result")

        ai_message = await self._save_message(
            owner_user_id=command.principal.id,
            speaker_type=SPEAKER_AI,
            speaker_agent_id=participant.id,
            speaker_name=participant.name,
            content=completed.content,
        )
        conversation.append((participant.name, completed.content))
        yield ConversationStreamEvent.message_persisted(_message_result(ai_message))

        async for stream_event in self._emit_consulted_replies(
            principal_id=command.principal.id,
            consultations=completed.consultations,
            conversation=conversation,
        ):
            yield stream_event

    async def _emit_consulted_replies(
        self,
        *,
        principal_id: uuid.UUID,
        consultations: tuple[ConsultedReply, ...],
        conversation: list[tuple[str, str]],
    ) -> AsyncIterator[ConversationStreamEvent]:
        for consulted in consultations:
            yield ConversationStreamEvent.turn_started(
                speaker_agent_id=consulted.participant_id,
                speaker_name=consulted.participant_name,
            )
            yield ConversationStreamEvent.delta(consulted.content)
            message = await self._save_message(
                owner_user_id=principal_id,
                speaker_type=SPEAKER_AI,
                speaker_agent_id=consulted.participant_id,
                speaker_name=consulted.participant_name,
                content=consulted.content,
            )
            conversation.append((consulted.participant_name, consulted.content))
            yield ConversationStreamEvent.message_persisted(_message_result(message))

    async def emit_orchestration(
        self,
        *,
        principal_id: uuid.UUID,
        assistant: Participant,
        orchestration: OrchestrationResult,
    ) -> AsyncIterator[ConversationStreamEvent]:
        yield ConversationStreamEvent.orchestration_snapshot(orchestration.payload)
        message = await self._save_message(
            owner_user_id=principal_id,
            speaker_type=SPEAKER_AI,
            speaker_agent_id=assistant.id,
            speaker_name=assistant.name,
            content=progress_text(orchestration.payload),
        )
        yield ConversationStreamEvent.message_persisted(_message_result(message))

    async def _history_days(self) -> int:
        return await self._configuration.integer("desktop_history_days", _DEFAULT_HISTORY_DAYS)

    async def _require_owned_message(
        self, owner_user_id: uuid.UUID, message_id: uuid.UUID
    ) -> ConversationMessage:
        async with self._uow_factory() as uow:
            message = await uow.messages.get_owned_message(owner_user_id, message_id)
        if message is None:
            raise ResourceNotFound("消息不存在")
        return message

    async def _resolve_reply_preview(
        self,
        owner_user_id: uuid.UUID,
        reply_to_message_id: uuid.UUID | None,
    ) -> ReplyPreview | None:
        if reply_to_message_id is None:
            return None
        message = await self._require_owned_message(owner_user_id, reply_to_message_id)
        return ReplyPreview(
            id=message.id,
            speaker_name=message.speaker_name,
            content=self._preview_text(message.content),
        )

    def _preview_text(self, content: str) -> str:
        compact = " ".join(content.split())
        if len(compact) <= _MAX_REPLY_PREVIEW_CHARS:
            return compact
        return compact[: _MAX_REPLY_PREVIEW_CHARS - 1] + "…"

    async def _save_message(
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
    ) -> ConversationMessage:
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
        return message
