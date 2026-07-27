"""Outer adapters for assistants, Agent runtime, workflow, config, and Knowledge."""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.contracts import ExecutionContext
from app.agents.skills import execute_all, fold_notes
from app.contexts.business.assistant_conversations.application.contracts import (
    AgentExecutionEvent,
    AgentExecutionRequest,
    ArchiveConversationRequest,
    ConsultedReply,
    OrchestrationResult,
    Principal,
)
from app.contexts.business.assistant_conversations.domain.models import Assistant, Participant
from app.contexts.foundations.knowledge.knowledge_indexing import public as knowledge_indexing
from app.contexts.foundations.knowledge.knowledge_indexing.contracts import IndexTextCommand
from app.contexts.foundations.knowledge.organizational_memory import public as organizational_memory
from app.contexts.foundations.knowledge.organizational_memory.contracts import (
    DistillConversationCommand,
)
from app.contexts.foundations.knowledge.wiki_management import public as wiki_management
from app.contexts.foundations.workforce.expert_management import public as expert_management
from app.contexts.shared_kernel import ResourceNotFound
from app.models.agent import AgentRole, AgentTaskRecord
from app.models.knowledge import SCOPE_PERSONAL, KnowledgeBase
from app.platform.object_storage import gateway as storage
from app.services import config_service, orchestration_service

logger = logging.getLogger(__name__)

_ASSISTANT_PROMPT = (
    "你是这位同事的专属AI助理，熟悉其工作、乐于协助。回答简明、务实、口吻亲切专业；"
    "遇到需要事实依据的问题优先引用可查资料并标注来源；不确定就说不确定，不编造。"
)

AgentStream = Callable[..., AsyncIterator[str | AgentTaskRecord]]
AgentRunner = Callable[..., Awaitable[AgentTaskRecord]]
LegacyDistill = Callable[..., Awaitable[str | None]]
LegacyIngest = Callable[..., Awaitable[object]]


class SQLAlchemyAssistantDirectoryAdapter:
    """Translate the personal-assistant convention over existing Agent/KB tables."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_or_create(self, principal: Principal) -> Assistant:
        user_id = principal.id
        display_name = principal.display_name
        roster = await expert_management.list_expert_roster(
            self._session,
            include_personal=True,
        )
        expert = next((item for item in roster if item.owner_user_id == user_id), None)
        if expert is None:
            base_name = f"{display_name}的助理"
            name_taken = any(item.name == base_name for item in roster)
            expert = await expert_management.create_expert(
                self._session,
                name=f"{base_name}-{user_id.hex[:4]}" if name_taken else base_name,
                prompt_template=_ASSISTANT_PROMPT,
                duty=None,
                model_role="daily",
                department_id=principal.department_id,
                permission_scope={},
                tools=[],
                title="专属助理",
                tier="member",
                report_to_id=None,
                owner_user_id=user_id,
            )
        knowledge_base_id = await self._personal_knowledge_base_id(expert.expert_id)
        if knowledge_base_id is None:
            knowledge_base = await wiki_management.create_knowledge_base(
                self._session,
                name=f"{display_name}的对话记忆",
                scope=SCOPE_PERSONAL,
                owner_agent_id=expert.expert_id,
                description="工作桌面归档的历史对话，仅本人助理可检索。",
            )
            knowledge_base_id = knowledge_base.id
        return Assistant(
            id=expert.expert_id,
            owner_user_id=user_id,
            name=expert.name,
            personal_knowledge_base_id=knowledge_base_id,
        )

    async def list_addable(self) -> tuple[Participant, ...]:
        statement = (
            select(AgentRole)
            .where(
                AgentRole.owner_user_id.is_(None),
                AgentRole.is_active.is_(True),
                AgentRole.is_delete.is_(False),
            )
            .order_by(AgentRole.tier, AgentRole.name)
        )
        return tuple(
            Participant(id=row.id, name=row.name, title=row.title)
            for row in (await self._session.execute(statement)).scalars()
        )

    async def resolve_addable(self, agent_ids: tuple[uuid.UUID, ...]) -> tuple[Participant, ...]:
        result: list[Participant] = []
        for agent_id in agent_ids:
            row = await self._session.get(AgentRole, agent_id)
            if row is None or row.is_delete or not row.is_active or row.owner_user_id is not None:
                raise ResourceNotFound("要加入的 AI 不存在或不可用")
            result.append(Participant(id=row.id, name=row.name, title=row.title))
        return tuple(result)

    async def _personal_knowledge_base_id(self, assistant_id: uuid.UUID) -> uuid.UUID | None:
        statement = select(KnowledgeBase.id).where(
            KnowledgeBase.scope == SCOPE_PERSONAL,
            KnowledgeBase.owner_agent_id == assistant_id,
            KnowledgeBase.is_delete.is_(False),
        )
        return (await self._session.execute(statement)).scalar_one_or_none()


class LegacyConfigurationAdapter:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def integer(self, key: str, default: int) -> int:
        try:
            return int(await config_service.resolve(self._session, key, default))
        except (TypeError, ValueError):
            return default


class LegacyAgentExecutionAdapter:
    """Keep the current streaming/skill behavior behind a plain-data port."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        agent_stream: AgentStream,
        agent_runner: AgentRunner,
    ) -> None:
        self._session = session
        self._agent_stream = agent_stream
        self._agent_runner = agent_runner

    def stream(self, request: AgentExecutionRequest) -> AsyncIterator[AgentExecutionEvent]:
        return self._stream(request)

    async def _stream(self, request: AgentExecutionRequest) -> AsyncIterator[AgentExecutionEvent]:
        role = await self._session.get(AgentRole, request.participant_id)
        if role is None:
            raise ResourceNotFound("智能体不存在")
        record: AgentTaskRecord | None = None
        async for item in self._agent_stream(
            self._session,
            role,
            task_type="desktop_chat",
            input_summary=f"桌面对话：{request.original_message[:40]}",
            user_message=request.prompt,
            user_id=request.principal_id,
            use_knowledge=True,
        ):
            if isinstance(item, AgentTaskRecord):
                record = item
            else:
                yield AgentExecutionEvent(name="delta", text=item)
        if record is None:
            raise RuntimeError("Agent reply completed without an execution record")
        reply = record.output_content or record.error_msg or "（无回应）"
        result = await execute_all(
            self._session,
            role,
            reply,
            user_id=request.principal_id,
            user_intent=request.original_message,
            execution_context=ExecutionContext(
                user_id=request.principal_id,
                user_intent=request.original_message,
                agent_runner=self._agent_runner,
            ),
        )
        reply = fold_notes(reply, result)
        consultations = tuple(
            ConsultedReply(
                participant_id=consulted.id,
                participant_name=consulted.name,
                content=(
                    consulted_record.output_content or consulted_record.error_msg or "（无回应）"
                ),
            )
            for consulted, consulted_record in result.consult_replies
        )
        yield AgentExecutionEvent(
            name="complete",
            content=reply,
            consultations=consultations,
        )


class LegacyOrchestrationAdapter:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def try_start(
        self,
        *,
        principal_id: uuid.UUID,
        assistant_id: uuid.UUID,
        message: str,
    ) -> OrchestrationResult | None:
        try:
            snapshot = await orchestration_service.start(
                self._session,
                message,
                creator_id=principal_id,
                assignee_agent_id=assistant_id,
                operator_id=principal_id,
            )
        except Exception:  # noqa: BLE001 - orchestration failure falls back to chat
            logger.warning("桌面编排启动失败，退回普通对话", exc_info=True)
            return None
        return OrchestrationResult(snapshot) if snapshot is not None else None


class PublishedConversationArchiveAdapter:
    """Archive through Organizational Memory and Knowledge Indexing contracts."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def archive(self, request: ArchiveConversationRequest) -> None:
        draft = await organizational_memory.distill_conversation(
            self._session,
            DistillConversationCommand(
                transcript=request.transcript,
                principal_id=request.principal_id,
                source_type="assistant_conversation",
            ),
        )
        title_suffix = "记忆" if draft is not None else "存档"
        await knowledge_indexing.index_text(
            self._session,
            IndexTextCommand(
                title=request.title_template.replace("{title_suffix}", title_suffix),
                text=draft.content if draft is not None else request.transcript,
                uploader_id=request.principal_id,
                knowledge_base_id=request.knowledge_base_id,
                category="conversation",
            ),
        )


class LegacyConversationArchiveAdapter:
    """Compatibility adapter retaining monkeypatchable legacy archive seams."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        distill: LegacyDistill,
        ingest: LegacyIngest,
    ) -> None:
        self._session = session
        self._distill = distill
        self._ingest = ingest

    async def archive(self, request: ArchiveConversationRequest) -> None:
        distilled = await self._distill(
            self._session,
            request.transcript,
            user_id=request.principal_id,
        )
        title_suffix = "记忆" if distilled else "存档"
        await self._ingest(
            self._session,
            title=request.title_template.replace("{title_suffix}", title_suffix),
            text=distilled or request.transcript,
            uploader_id=request.principal_id,
            knowledge_base_id=request.knowledge_base_id,
            category="conversation",
        )


class KnowledgeAttachmentStorageAdapter:
    async def put(self, *, object_name: str, content: bytes, content_type: str) -> str:
        return await storage.put_object(object_name, content, content_type)

    async def get(self, *, object_name: str) -> bytes:
        return await storage.get_object_bytes(object_name)


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class UUIDIdentifier:
    def new_id(self) -> uuid.UUID:
        return uuid.uuid4()

    def new_object_token(self) -> str:
        return uuid.uuid4().hex


async def legacy_try_orchestrate(
    session: AsyncSession,
    *,
    principal_id: uuid.UUID,
    assistant_id: uuid.UUID,
    message: str,
) -> dict[str, Any] | None:
    result = await LegacyOrchestrationAdapter(session).try_start(
        principal_id=principal_id,
        assistant_id=assistant_id,
        message=message,
    )
    return dict(result.payload) if result is not None else None
