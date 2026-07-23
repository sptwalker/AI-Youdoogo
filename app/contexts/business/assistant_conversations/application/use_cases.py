"""Assistant Conversations use cases and transaction ownership."""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from datetime import timedelta

from app.contexts.business.assistant_conversations.application.contracts import (
    AgentExecutionRequest,
    AgentResult,
    ArchiveConversationRequest,
    AssistantResult,
    ConversationResult,
    ConversationStreamEvent,
    MessageResult,
    OrchestrationResult,
    Principal,
    SendMessageCommand,
)
from app.contexts.business.assistant_conversations.application.ports import (
    AgentExecutionPort,
    AssistantDirectoryPort,
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
    deduplicate_added_agents,
    ensure_added_agent_limit,
    progress_text,
    round_count,
    roundtable_prompt,
)

_DEFAULT_HISTORY_DAYS = 10

logger = logging.getLogger(__name__)


def _assistant_result(assistant: Assistant) -> AssistantResult:
    return AssistantResult(
        id=assistant.id,
        owner_user_id=assistant.owner_user_id,
        name=assistant.name,
    )


def _agent_result(agent: Participant) -> AgentResult:
    return AgentResult(id=agent.id, name=agent.name, title=agent.title)


def _message_result(message: ConversationMessage) -> MessageResult:
    return MessageResult(
        id=message.id,
        speaker_type=message.speaker_type,
        speaker_agent_id=message.speaker_agent_id,
        speaker_name=message.speaker_name,
        content=message.content,
        create_time=message.create_time,
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
        clock: Clock,
        identifiers: IdentifierPort,
    ) -> None:
        self._uow_factory = uow_factory
        self._assistants = assistants
        self._configuration = configuration
        self._agents = agents
        self._orchestration = orchestration
        self._archive_port = archive_port
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
        ensure_added_agent_limit(command.add_agent_ids, max_add=command.max_add)
        assistant = await self._assistants.get_or_create(principal)
        added_ids = deduplicate_added_agents(
            command.add_agent_ids,
            assistant_id=assistant.id,
            max_add=command.max_add,
        )
        added = await self._assistants.resolve_addable(added_ids)
        participants = (Participant(assistant.id, assistant.name), *added)

        configured_rounds = await self._configuration.integer(
            "desktop_roundtable_rounds", command.default_rounds
        )
        rounds = round_count(
            configured_rounds,
            participant_count=len(participants),
            maximum=command.max_rounds,
        )
        async with self._uow_factory() as uow:
            recent = await uow.messages.list_recent(
                principal.id,
                limit=command.recent_context,
            )
        conversation = tuple((message.speaker_name, message.content) for message in recent)

        user_message = await self._save_message(
            owner_user_id=principal.id,
            speaker_type=SPEAKER_USER,
            speaker_name=principal.display_name,
            content=command.message,
        )
        conversation += ((principal.display_name, command.message),)
        yield ConversationStreamEvent("message_end", _message_result(user_message).as_dict())

        if len(participants) == 1:
            orchestration = await self._orchestration.try_start(
                principal_id=principal.id,
                assistant_id=assistant.id,
                message=command.message,
            )
            if orchestration is not None:
                async for stream_event in self.emit_orchestration(
                    principal_id=principal.id,
                    assistant=Participant(assistant.id, assistant.name),
                    orchestration=orchestration,
                ):
                    yield stream_event
                return

        for _round in range(rounds):
            for participant in participants:
                prompt = roundtable_prompt(participant, participants, conversation)
                yield ConversationStreamEvent(
                    "message_start",
                    {
                        "speaker_agent_id": str(participant.id),
                        "speaker_name": participant.name,
                    },
                )
                completed = None
                async for agent_event in self._agents.stream(
                    AgentExecutionRequest(
                        participant_id=participant.id,
                        principal_id=principal.id,
                        original_message=command.message,
                        prompt=prompt,
                    )
                ):
                    if agent_event.name == "delta":
                        yield ConversationStreamEvent("delta", {"text": agent_event.text})
                    elif agent_event.name == "complete":
                        completed = agent_event
                if completed is None:
                    raise RuntimeError("Agent reply completed without an execution result")
                ai_message = await self._save_message(
                    owner_user_id=principal.id,
                    speaker_type=SPEAKER_AI,
                    speaker_agent_id=participant.id,
                    speaker_name=participant.name,
                    content=completed.content,
                )
                conversation += ((participant.name, completed.content),)
                yield ConversationStreamEvent("message_end", _message_result(ai_message).as_dict())

                for consulted in completed.consultations:
                    yield ConversationStreamEvent(
                        "message_start",
                        {
                            "speaker_agent_id": str(consulted.participant_id),
                            "speaker_name": consulted.participant_name,
                        },
                    )
                    yield ConversationStreamEvent("delta", {"text": consulted.content})
                    consulted_message = await self._save_message(
                        owner_user_id=principal.id,
                        speaker_type=SPEAKER_AI,
                        speaker_agent_id=consulted.participant_id,
                        speaker_name=consulted.participant_name,
                        content=consulted.content,
                    )
                    conversation += ((consulted.participant_name, consulted.content),)
                    yield ConversationStreamEvent(
                        "message_end",
                        _message_result(consulted_message).as_dict(),
                    )

    async def emit_orchestration(
        self,
        *,
        principal_id: uuid.UUID,
        assistant: Participant,
        orchestration: OrchestrationResult,
    ) -> AsyncIterator[ConversationStreamEvent]:
        yield ConversationStreamEvent("orchestration", dict(orchestration.payload))
        message = await self._save_message(
            owner_user_id=principal_id,
            speaker_type=SPEAKER_AI,
            speaker_agent_id=assistant.id,
            speaker_name=assistant.name,
            content=progress_text(orchestration.payload),
        )
        yield ConversationStreamEvent("message_end", _message_result(message).as_dict())

    async def _history_days(self) -> int:
        return await self._configuration.integer("desktop_history_days", _DEFAULT_HISTORY_DAYS)

    async def _save_message(
        self,
        *,
        owner_user_id: uuid.UUID,
        speaker_type: str,
        speaker_name: str,
        content: str,
        speaker_agent_id: uuid.UUID | None = None,
    ) -> ConversationMessage:
        message = ConversationMessage(
            id=self._identifiers.new_id(),
            owner_user_id=owner_user_id,
            speaker_type=speaker_type,
            speaker_agent_id=speaker_agent_id,
            speaker_name=speaker_name,
            content=content,
            create_time=self._clock.now(),
        )
        async with self._uow_factory() as uow:
            await uow.messages.add(message)
            await uow.commit()
        return message
