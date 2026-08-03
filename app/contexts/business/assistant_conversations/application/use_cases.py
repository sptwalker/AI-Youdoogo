"""Assistant conversation lifecycle, persistence, and stream ordering."""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import timedelta

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
    SendMessageCommand,
    conversation_archive_document_id,
)
from app.contexts.business.assistant_conversations.application.message_store import (
    ConversationMessageStore,
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
    Participant,
    deduplicate_added_agents,
    describe_user_turn,
    direct_chat_prompt,
    ensure_added_agent_limit,
    progress_text,
    round_count,
    roundtable_prompt,
)
from app.contexts.shared_kernel import InvalidInput, PermissionDenied, RuleViolation

_DEFAULT_HISTORY_DAYS = 10
_MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024
_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")
logger = logging.getLogger(__name__)


class AssistantConversationsApplication:
    """Own the conversation lifecycle behind one request-scoped application API."""

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
        self._messages = ConversationMessageStore(
            uow_factory=uow_factory,
            clock=clock,
            identifiers=identifiers,
        )
        self._assistants = assistants
        self._configuration = configuration
        self._agents = agents
        self._orchestration = orchestration
        self._archive_port = archive_port
        self._attachment_storage = attachment_storage
        self._clock = clock
        self._identifiers = identifiers

    async def get_or_create_assistant(self, principal: Principal) -> AssistantResult:
        assistant = await self._assistants.get_or_create(principal)
        return AssistantResult(
            id=assistant.id,
            owner_user_id=assistant.owner_user_id,
            name=assistant.name,
        )

    async def list_addable_agents(self) -> tuple[AgentResult, ...]:
        return tuple(
            AgentResult(id=agent.id, name=agent.name, title=agent.title)
            for agent in await self._assistants.list_addable()
        )

    async def get_conversation(self, principal: Principal) -> ConversationResult:
        assistant = await self._assistants.get_or_create(principal)
        days = await self._configuration.integer("desktop_history_days", _DEFAULT_HISTORY_DAYS)
        await self._archive_old(principal, days=days, assistant=assistant)
        messages = await self._messages.list_since(
            principal.id,
            since=self._clock.now() - timedelta(days=days),
        )
        addable = await self._assistants.list_addable()
        return ConversationResult(
            assistant=AssistantResult(
                id=assistant.id,
                owner_user_id=assistant.owner_user_id,
                name=assistant.name,
            ),
            messages=messages,
            addable_agents=tuple(
                AgentResult(id=agent.id, name=agent.name, title=agent.title)
                for agent in addable
            ),
        )

    async def list_messages(self, principal: Principal) -> tuple[MessageResult, ...]:
        days = await self._configuration.integer("desktop_history_days", _DEFAULT_HISTORY_DAYS)
        await self._archive_old(principal, days=days)
        return await self._messages.list_since(
            principal.id,
            since=self._clock.now() - timedelta(days=days),
        )

    async def archive_old(self, principal: Principal, *, days: int | None = None) -> int:
        return await self._archive_old(
            principal,
            days=(
                days
                if days is not None
                else await self._configuration.integer(
                    "desktop_history_days", _DEFAULT_HISTORY_DAYS
                )
            ),
        )

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
            attachment_type=(
                "image" if safe_name.lower().endswith(_IMAGE_EXTENSIONS) else "file"
            ),
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
        if not await self._messages.attachment_visible_to_user(
            storage_path=storage_path,
            user_id=user_id,
        ):
            raise PermissionDenied("无权访问该附件")
        return AttachmentDownloadResult(
            name=name,
            content=await self._attachment_storage.get(object_name=object_name),
        )

    async def pin_message(
        self,
        *,
        owner_user_id: uuid.UUID,
        message_id: uuid.UUID,
        pinned_by_user_id: uuid.UUID,
    ) -> MessageResult:
        message = await self._messages.require_owned(owner_user_id, message_id)
        if message.is_pinned:
            return self._messages.as_result(message)
        return await self._messages.save_existing(
            replace(
                message,
                is_pinned=True,
                pinned_at=self._clock.now(),
                pinned_by_user_id=pinned_by_user_id,
            )
        )

    async def unpin_message(
        self,
        *,
        owner_user_id: uuid.UUID,
        message_id: uuid.UUID,
    ) -> MessageResult:
        message = await self._messages.require_owned(owner_user_id, message_id)
        if not message.is_pinned:
            return self._messages.as_result(message)
        return await self._messages.save_existing(
            replace(
                message,
                is_pinned=False,
                pinned_at=None,
                pinned_by_user_id=None,
            )
        )

    async def send_message_stream(
        self, command: SendMessageCommand
    ) -> AsyncIterator[ConversationStreamEvent]:
        principal = command.principal
        ensure_added_agent_limit(command.add_agent_ids, max_add=command.max_add)
        assistant = await self._assistants.get_or_create(principal)
        added_ids = deduplicate_added_agents(
            command.add_agent_ids,
            assistant_id=assistant.id,
            max_add=command.max_add,
        )
        participants = (
            Participant(assistant.id, assistant.name),
            *await self._assistants.resolve_addable(added_ids),
        )
        rounds = round_count(
            await self._configuration.integer(
                "desktop_roundtable_rounds", command.default_rounds
            ),
            participant_count=len(participants),
            maximum=command.max_rounds,
        )
        conversation = await self._messages.list_recent(
            principal.id,
            limit=command.recent_context,
        )
        reply_preview = await self._messages.reply_preview(
            principal.id,
            command.reply_to_message_id,
        )
        user_message = await self._messages.add(
            owner_user_id=principal.id,
            speaker_type=SPEAKER_USER,
            speaker_name=principal.display_name,
            content=command.message,
            reply_to_message_id=command.reply_to_message_id,
            reply_preview=reply_preview,
            attachments=command.attachments,
        )
        conversation.append(
            (principal.display_name, describe_user_turn(command.message, command.attachments))
        )
        yield ConversationStreamEvent.message_persisted(user_message)

        orchestration = (
            None
            if len(participants) != 1 or command.attachments
            else await self._orchestration.try_start(
                principal_id=principal.id,
                assistant_id=assistant.id,
                message=command.message,
            )
        )
        if orchestration is not None:
            async for event in self.emit_orchestration(
                principal_id=principal.id,
                assistant=participants[0],
                orchestration=orchestration,
            ):
                yield event
            return
        async for event in self._emit_roundtable(
            command=command,
            participants=participants,
            rounds=rounds,
            conversation=conversation,
        ):
            yield event

    async def emit_orchestration(
        self,
        *,
        principal_id: uuid.UUID,
        assistant: Participant,
        orchestration: OrchestrationResult,
    ) -> AsyncIterator[ConversationStreamEvent]:
        yield ConversationStreamEvent.orchestration_snapshot(orchestration.payload)
        message = await self._messages.add(
            owner_user_id=principal_id,
            speaker_type=SPEAKER_AI,
            speaker_agent_id=assistant.id,
            speaker_name=assistant.name,
            content=progress_text(orchestration.payload),
        )
        yield ConversationStreamEvent.message_persisted(message)

    async def _archive_old(
        self,
        principal: Principal,
        *,
        days: int,
        assistant: Assistant | None = None,
    ) -> int:
        old = await self._messages.list_before(
            principal.id,
            before=self._clock.now() - timedelta(days=days),
        )
        if not old:
            return 0
        assistant = assistant or await self._assistants.get_or_create(principal)
        if assistant.personal_knowledge_base_id is None:
            return 0
        message_ids = tuple(message.id for message in old)
        try:
            await self._archive_port.archive(
                ArchiveConversationRequest(
                    principal_id=principal.id,
                    knowledge_base_id=assistant.personal_knowledge_base_id,
                    document_id=conversation_archive_document_id(principal.id, message_ids),
                    title_template=(
                        f"{principal.display_name}对话{{title_suffix}} "
                        f"{old[0].create_time:%Y-%m-%d} ~ {old[-1].create_time:%Y-%m-%d}"
                    ),
                    transcript="\n".join(
                        f"{message.speaker_name}：{message.content}" for message in old
                    ),
                )
            )
        except Exception:  # noqa: BLE001 - preserve retry-on-next-load behavior
            logger.warning(
                "对话归档入库失败 user=%s，保留消息下次重试",
                principal.id,
                exc_info=True,
            )
            return 0
        await self._messages.delete(message_ids)
        return len(message_ids)

    async def _emit_roundtable(
        self,
        *,
        command: SendMessageCommand,
        participants: tuple[Participant, ...],
        rounds: int,
        conversation: list[tuple[str, str]],
    ) -> AsyncIterator[ConversationStreamEvent]:
        for _ in range(rounds):
            for participant in participants:
                async for event in self._emit_participant_turn(
                    command=command,
                    participant=participant,
                    participants=participants,
                    conversation=conversation,
                ):
                    yield event

    async def _emit_participant_turn(
        self,
        *,
        command: SendMessageCommand,
        participant: Participant,
        participants: tuple[Participant, ...],
        conversation: list[tuple[str, str]],
    ) -> AsyncIterator[ConversationStreamEvent]:
        prompt = (
            direct_chat_prompt(participant, tuple(conversation))
            if len(participants) == 1
            else roundtable_prompt(participant, participants, tuple(conversation))
        )
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
        message = await self._messages.add(
            owner_user_id=command.principal.id,
            speaker_type=SPEAKER_AI,
            speaker_agent_id=participant.id,
            speaker_name=participant.name,
            content=completed.content,
        )
        conversation.append((participant.name, completed.content))
        yield ConversationStreamEvent.message_persisted(message)
        async for event in self._emit_consulted_replies(
            principal_id=command.principal.id,
            consultations=completed.consultations,
            conversation=conversation,
        ):
            yield event

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
            message = await self._messages.add(
                owner_user_id=principal_id,
                speaker_type=SPEAKER_AI,
                speaker_agent_id=consulted.participant_id,
                speaker_name=consulted.participant_name,
                content=consulted.content,
            )
            conversation.append((consulted.participant_name, consulted.content))
            yield ConversationStreamEvent.message_persisted(message)
