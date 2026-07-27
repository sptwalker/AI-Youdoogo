"""Outer adapters for Agent, realtime, storage, archive, promotion, and Outbox."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

import app.platform.object_storage.gateway as storage
from app.agents.base import run_agent, run_agent_stream
from app.agents.contracts import ExecutionContext
from app.agents.skills import execute_all, fold_notes
from app.contexts.business.group_messaging.application.contracts import (
    DISBAND_ARCHIVE_EVENT,
    AgentReplyRequest,
    AgentReplyStreamEvent,
    ArchiveRequest,
    MessageStreamEvent,
    PromotionRequest,
)
from app.contexts.business.group_messaging.infrastructure.sqlalchemy_repository import (
    SQLAlchemyGroupMessagingRepository,
)
from app.contexts.foundations.knowledge.knowledge_indexing import (
    public as knowledge_indexing,
)
from app.contexts.foundations.knowledge.knowledge_indexing.contracts import (
    IndexTextCommand,
)
from app.contexts.foundations.knowledge.organizational_memory import (
    public as organizational_memory,
)
from app.contexts.foundations.knowledge.organizational_memory.contracts import (
    DistillConversationCommand,
)
from app.contexts.foundations.knowledge.wiki_management import public as wiki_management
from app.models.agent import AgentRole, AgentTaskRecord
from app.platform import realtime
from app.services import outbox_service, proposal_service, task_service


class RedisRealtimeDeliveryAdapter:
    async def publish(
        self, channel_id: uuid.UUID, event_name: str, data: dict[str, object]
    ) -> None:
        await realtime.publish(str(channel_id), event_name, data)


class RedisRealtimeSubscriptionAdapter:
    def subscribe_user(
        self, *, user_id: uuid.UUID, channel_ids: tuple[uuid.UUID, ...]
    ) -> AsyncIterator[MessageStreamEvent]:
        return self._subscribe_user(user_id=user_id, channel_ids=channel_ids)

    async def _subscribe_user(
        self, *, user_id: uuid.UUID, channel_ids: tuple[uuid.UUID, ...]
    ) -> AsyncIterator[MessageStreamEvent]:
        from app.core.database import async_session_factory

        async def _still_member(channel_id: str) -> bool:
            try:
                parsed_channel_id = uuid.UUID(channel_id)
            except ValueError:
                return False
            async with async_session_factory() as session:
                repository = SQLAlchemyGroupMessagingRepository(session)
                return await repository.is_member(parsed_channel_id, user_id)

        async for name, data in realtime.subscribe(
            [str(channel_id) for channel_id in channel_ids],
            authorize=_still_member,
        ):
            yield MessageStreamEvent(name=name, data=data)


class LegacyAgentReplyAdapter:
    """Translate current Agent runtime records into Group Messaging reply events."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def stream(self, request: AgentReplyRequest) -> AsyncIterator[AgentReplyStreamEvent]:
        return self._stream(request)

    async def _stream(self, request: AgentReplyRequest) -> AsyncIterator[AgentReplyStreamEvent]:
        role = await self._session.get(AgentRole, request.agent_id)
        if role is None or role.is_delete or not role.is_active:
            return
        yield AgentReplyStreamEvent(
            name="start",
            speaker_agent_id=role.id,
            speaker_name=role.name,
        )
        user_message = (
            f"你在企业协作频道「{request.channel_name}」中被 @ 点名。\n\n"
            f"频道近期讨论：\n{request.recent_context}\n\n"
            "请以你的角色身份，就上文给出一段简明的参考意见/建议（仅供真人参考）。"
        )
        record: AgentTaskRecord | None = None
        async for item in run_agent_stream(
            self._session,
            role,
            task_type="discussion_reply",
            input_summary=f"讨论回复：{request.content[:40]}",
            user_message=user_message,
            user_id=request.user_id,
        ):
            if isinstance(item, AgentTaskRecord):
                record = item
            else:
                yield AgentReplyStreamEvent(name="delta", text=item)
        if record is None:
            raise RuntimeError("Agent reply completed without an execution record")
        reply = record.output_content or record.error_msg or "（无产出）"
        protocol_result = await execute_all(
            self._session,
            role,
            reply,
            user_id=request.user_id,
            execution_context=ExecutionContext(
                user_id=request.user_id,
                agent_runner=run_agent,
            ),
        )
        reply = fold_notes(reply, protocol_result)
        yield AgentReplyStreamEvent(
            name="complete",
            speaker_agent_id=role.id,
            speaker_name=role.name,
            content=reply,
            source_record_id=record.id,
        )
        for consulted, consulted_record in protocol_result.consult_replies:
            answer = consulted_record.output_content or consulted_record.error_msg or "（无回应）"
            yield AgentReplyStreamEvent(
                name="start",
                speaker_agent_id=consulted.id,
                speaker_name=consulted.name,
            )
            yield AgentReplyStreamEvent(name="delta", text=answer)
            yield AgentReplyStreamEvent(
                name="complete",
                speaker_agent_id=consulted.id,
                speaker_name=consulted.name,
                content=answer,
                source_record_id=consulted_record.id,
                publish_realtime=False,
            )


class KnowledgeAttachmentStorageAdapter:
    async def put(self, *, object_name: str, content: bytes, content_type: str) -> str:
        return await storage.put_object(object_name, content, content_type)

    async def get(self, *, object_name: str) -> bytes:
        return await storage.get_object_bytes(object_name)


class OrganizationalMemoryArchiveAdapter:
    """Caller-owned translation into current Knowledge and Memory capabilities."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def archive(self, request: ArchiveRequest) -> None:
        draft = await organizational_memory.distill_conversation(
            self._session,
            DistillConversationCommand(
                transcript=request.transcript,
                principal_id=request.creator_id,
                source_type="discussion_channel",
                source_id=request.channel_id,
            ),
        )
        knowledge_base = await wiki_management.get_default_knowledge_base(self._session)
        await knowledge_indexing.index_text(
            self._session,
            IndexTextCommand(
                title=f"群聊存档·{request.channel_name}",
                text=draft.content if draft is not None else request.transcript,
                uploader_id=request.creator_id,
                knowledge_base_id=knowledge_base.id,
                category="discussion",
                document_id=request.file_id,
            ),
        )


class LegacyPromotionAdapter:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def promote(self, request: PromotionRequest) -> uuid.UUID:
        if request.target == "proposal":
            proposal = await proposal_service.create_proposal(
                self._session,
                title=request.title,
                background=request.content,
                plan="（讨论升格，方案待补充）",
                creator_id=request.creator_id,
            )
            return proposal.id
        task = await task_service.create_task(
            self._session,
            title=request.title,
            task_type="manual",
            creator_id=request.creator_id,
            payload={"from_message_id": str(request.source_message_id)},
        )
        return task.id


class SQLAlchemyOutboxAdapter:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def enqueue_disband_archive(self, channel_id: uuid.UUID) -> None:
        await outbox_service.enqueue(
            self._session,
            aggregate_type="discussion_channel",
            aggregate_id=channel_id,
            event_type=DISBAND_ARCHIVE_EVENT,
            dedupe_key=f"discussion-channel:{channel_id}:archive:v1",
            payload={"channel_id": str(channel_id)},
        )


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class UUIDIdentifier:
    def new_id(self) -> uuid.UUID:
        return uuid.uuid4()

    def new_object_token(self) -> str:
        return uuid.uuid4().hex
