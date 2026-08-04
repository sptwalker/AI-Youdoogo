"""Outer adapters for assistants, Agent runtime, workflow, config, and Knowledge."""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.contracts import ExecutionContext, agent_execution_result
from app.agents.tool_dispatcher import ToolDispatcher
from app.contexts.business.assistant_conversations.application.contracts import (
    AgentExecutionEvent,
    AgentExecutionRequest,
    ArchiveConversationRequest,
    ConsultedReply,
    OrchestrationResult,
    Principal,
)
from app.contexts.business.assistant_conversations.domain.models import Assistant, Participant
from app.contexts.business.task_management import public as task_management
from app.contexts.foundations.execution.agent_execution import public as agent_execution
from app.contexts.foundations.execution.agent_execution.contracts.execution import (
    AgentExecutionRequest as FoundationAgentExecutionRequest,
)
from app.contexts.foundations.execution.agent_execution.contracts.execution import (
    AgentExecutionResult,
)
from app.contexts.foundations.execution.work_planning import public as work_planning
from app.contexts.foundations.execution.workflow_runtime import public as workflow_runtime
from app.contexts.foundations.governance.system_configuration import (
    public as system_configuration,
)
from app.contexts.foundations.knowledge.knowledge_indexing import public as knowledge_indexing
from app.contexts.foundations.knowledge.knowledge_indexing.contracts import IndexTextCommand
from app.contexts.foundations.knowledge.organizational_memory import public as organizational_memory
from app.contexts.foundations.knowledge.organizational_memory.contracts import (
    DistillConversationCommand,
)
from app.contexts.foundations.knowledge.wiki_management import public as wiki_management
from app.contexts.foundations.workforce.expert_management import public as expert_management
from app.contexts.shared_kernel import ResourceNotFound
from app.models.knowledge import SCOPE_PERSONAL, KnowledgeBase
from app.platform.object_storage import gateway as storage

logger = logging.getLogger(__name__)

_ASSISTANT_PROMPT = (
    "你是这位同事的专属AI助理，熟悉其工作、乐于协助。回答简明、务实、口吻亲切专业；"
    "遇到需要事实依据的问题优先引用可查资料并标注来源；不确定就说不确定，不编造。"
)

AgentStream = Callable[..., AsyncIterator[str | object]]
AgentRunner = Callable[..., Awaitable[object]]
LegacyDistill = Callable[..., Awaitable[str | None]]
LegacyIngest = Callable[..., Awaitable[object]]


class SQLAlchemyAssistantDirectoryAdapter:
    """Translate the personal-assistant convention over existing Agent/KB tables."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._experts = expert_management.build_local_expert_directory_port(session)

    async def get_or_create(self, principal: Principal) -> Assistant:
        user_id = principal.id
        display_name = principal.display_name
        roster = await self._experts.list_roster(include_personal=True)
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
        roster = await self._experts.list_roster(include_personal=False)
        return tuple(
            Participant(id=item.expert_id, name=item.name, title=item.title)
            for item in sorted(
                (item for item in roster if item.is_active),
                key=lambda item: (item.tier, item.name),
            )
        )

    async def resolve_addable(self, agent_ids: tuple[uuid.UUID, ...]) -> tuple[Participant, ...]:
        result: list[Participant] = []
        for agent_id in agent_ids:
            item = await self._experts.get_roster(agent_id)
            if item is None or not item.is_active or item.owner_user_id is not None:
                raise ResourceNotFound("要加入的 AI 不存在或不可用")
            result.append(Participant(id=item.expert_id, name=item.name, title=item.title))
        return tuple(result)

    async def _personal_knowledge_base_id(self, assistant_id: uuid.UUID) -> uuid.UUID | None:
        statement = select(KnowledgeBase.id).where(
            KnowledgeBase.scope == SCOPE_PERSONAL,
            KnowledgeBase.owner_agent_id == assistant_id,
            KnowledgeBase.is_delete.is_(False),
        )
        return (await self._session.execute(statement)).scalar_one_or_none()


class PublishedConfigurationAdapter:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def integer(self, key: str, default: int) -> int:
        try:
            resolved = await system_configuration.resolve_configuration(
                self._session,
                key,
                default,
            )
            return int(resolved) if isinstance(resolved, (int, float, str)) else default
        except (TypeError, ValueError):
            return default


class LegacyAgentExecutionAdapter:
    """Keep the current streaming/skill behavior behind a plain-data port."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        agent_stream: AgentStream | None,
        agent_runner: AgentRunner,
    ) -> None:
        self._session = session
        self._experts = expert_management.build_local_expert_directory_port(session)
        self._agent_stream = agent_stream
        self._agent_runner = agent_runner

    def stream(self, request: AgentExecutionRequest) -> AsyncIterator[AgentExecutionEvent]:
        return self._stream(request)

    async def _stream(self, request: AgentExecutionRequest) -> AsyncIterator[AgentExecutionEvent]:
        expert = await self._experts.get_execution(request.participant_id)
        if expert is None:
            raise ResourceNotFound("智能体不存在")
        execution_request = FoundationAgentExecutionRequest(
            expert=expert,
            task_type="desktop_chat",
            input_summary=f"桌面对话：{request.original_message[:40]}",
            user_message=request.prompt,
            user_id=request.principal_id,
            use_knowledge=True,
        )
        execution_result: AgentExecutionResult | None = None
        if self._agent_stream is not None:
            # Explicitly injected legacy streams remain available to tests and
            # bootstrap callers while the default path uses the pure contract.
            async for item in self._agent_stream(
                self._session,
                expert,
                task_type="desktop_chat",
                input_summary=f"桌面对话：{request.original_message[:40]}",
                user_message=request.prompt,
                user_id=request.principal_id,
                use_knowledge=True,
            ):
                if isinstance(item, str):
                    yield AgentExecutionEvent(name="delta", text=item)
                else:
                    execution_result = agent_execution_result(item)
        else:
            async for event in agent_execution.stream_agent(self._session, execution_request):
                if event.delta is not None:
                    yield AgentExecutionEvent(name="delta", text=event.delta)
                elif event.result is not None:
                    execution_result = event.result
        if execution_result is None:
            raise RuntimeError("Agent reply completed without an execution record")
        reply = execution_result.output_content or execution_result.error_msg or "（无回应）"
        protocol_result = await ToolDispatcher().dispatch_text(
            self._session,
            expert,
            reply,
            ExecutionContext(
                user_id=request.principal_id,
                user_intent=request.original_message,
                agent_runner=self._agent_runner,
            ),
            user_id=request.principal_id,
            user_intent=request.original_message,
        )
        reply = protocol_result.fold_notes(reply)
        consultations = tuple(
            ConsultedReply(
                participant_id=consulted.id,
                participant_name=consulted.name,
                content=(
                    consulted_record.output_content or consulted_record.error_msg or "（无回应）"
                ),
            )
            for consulted, consulted_record in protocol_result.consult_replies
        )
        yield AgentExecutionEvent(
            name="complete",
            content=reply,
            consultations=consultations,
        )


class PublishedOrchestrationAdapter:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def try_start(
        self,
        *,
        principal_id: uuid.UUID,
        assistant_id: uuid.UUID,
        message: str,
    ) -> OrchestrationResult | None:
        normalized = message.strip()
        if len(normalized) < 8:
            return None
        try:
            planned = await work_planning.plan_work(
                work_planning.PlanWorkRequest(
                    work_planning.WorkIntent(
                        request=normalized,
                        creator_id=principal_id,
                        assignee_expert_id=assistant_id,
                    )
                )
            )
            if planned.plan is None:
                return None
            started = await task_management.start_workflow(
                self._session,
                workflow_runtime.planning_to_start_command(planned.plan),
            )
            snapshot = await task_management.orchestration_progress(
                self._session,
                started.parent_task_id,
            )
        except Exception:  # noqa: BLE001 - orchestration failure falls back to chat
            await self._session.rollback()
            logger.warning("桌面编排启动失败，退回普通对话", exc_info=True)
            return None
        return OrchestrationResult(snapshot)


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
                document_id=request.document_id,
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




async def legacy_try_orchestrate(
    session: AsyncSession,
    *,
    principal_id: uuid.UUID,
    assistant_id: uuid.UUID,
    message: str,
) -> dict[str, Any] | None:
    result = await PublishedOrchestrationAdapter(session).try_start(
        principal_id=principal_id,
        assistant_id=assistant_id,
        message=message,
    )
    return dict(result.payload) if result is not None else None
