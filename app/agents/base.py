"""One-way compatibility facade for the Agent Execution bounded context."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.contracts import ExecutionContext
from app.agents.runtime_adapters import (
    LegacyKnowledgeAugmentationAdapter,
    LegacyPromptAssemblyAdapter,
)
from app.contexts.foundations.execution.agent_execution.application.knowledge import (
    KB_CLOSE as _KB_CLOSE,
)
from app.contexts.foundations.execution.agent_execution.application.knowledge import (
    KB_DEFENSE as _KB_DEFENSE,
)
from app.contexts.foundations.execution.agent_execution.application.knowledge import (
    KB_OPEN as _KB_OPEN,
)
from app.contexts.foundations.execution.agent_execution.application.knowledge import (
    build_knowledge_block as _build_knowledge_block,
)
from app.contexts.foundations.execution.agent_execution.application.ports import (
    AgentExecutionPort,
)
from app.contexts.foundations.execution.agent_execution.application.prompts import (
    DEFAULT_GLOBAL_PROMPT as _DEFAULT_GLOBAL_PROMPT,
)
from app.contexts.foundations.execution.agent_execution.application.use_cases import (
    llm_role_for,
)
from app.contexts.foundations.execution.agent_execution.contracts.execution import (
    AgentExecutionRequest,
    ExecutionTrace,
)
from app.contexts.foundations.execution.agent_execution.infrastructure.composition import (
    select_agent_execution,
)
from app.contexts.foundations.execution.agent_execution.infrastructure.langchain_gateway import (
    CurrentUsageAuthorizationAdapter,
)
from app.contexts.foundations.execution.agent_execution.infrastructure.sqlalchemy_recorder import (
    SQLAlchemyAgentExecutionRecorder,
)
from app.contexts.foundations.execution.agent_execution.infrastructure.system_clock import (
    SystemExecutionClock,
)
from app.contexts.foundations.workforce.expert_management.infrastructure.sqlalchemy_query import (
    SQLAlchemyExpertSnapshotQuery,
    snapshot_from_role,
)
from app.llm.usage import budget_exceeded, record_usage
from app.models.agent import AgentRole, AgentTaskRecord
from app.services import config_service as config_service

__all__ = [
    "_DEFAULT_GLOBAL_PROMPT",
    "_KB_CLOSE",
    "_KB_DEFENSE",
    "_KB_OPEN",
    "build_knowledge_block",
    "get_agent_role",
    "get_agent_role_by_code",
    "run_agent",
    "run_agent_stream",
]


async def get_agent_role(db: AsyncSession, name: str) -> AgentRole | None:
    return await SQLAlchemyExpertSnapshotQuery(db).get_record_by_name(name)


async def get_agent_role_by_code(db: AsyncSession, code: str) -> AgentRole | None:
    return await SQLAlchemyExpertSnapshotQuery(db).get_record_by_code(code)


def build_knowledge_block(materials: list[tuple[str, str]], user_message: str) -> str:
    return _build_knowledge_block(tuple(materials), user_message)


async def _inject_knowledge(
    db: AsyncSession, role: AgentRole, user_message: str
) -> tuple[str, list[dict[str, str | int]]]:
    augmentation = await LegacyKnowledgeAugmentationAdapter(db, role).augment(
        snapshot_from_role(role), user_message
    )
    return augmentation.message, [
        {
            "file_id": source.file_id,
            "file_name": source.file_name,
            "chunk_index": source.chunk_index,
        }
        for source in augmentation.sources
    ]


async def _prepare(
    db: AsyncSession, role: AgentRole, user_message: str, use_knowledge: bool
) -> tuple[str, str, str, list[dict[str, str | int]]]:
    snapshot = snapshot_from_role(role)
    system_prompt = await LegacyPromptAssemblyAdapter(
        db, role, _DEFAULT_GLOBAL_PROMPT
    ).build(snapshot)
    if not use_knowledge:
        return llm_role_for(snapshot.model_role), system_prompt, user_message, []
    message, sources = await _inject_knowledge(db, role, user_message)
    return llm_role_for(snapshot.model_role), system_prompt, message, sources


def _application(db: AsyncSession, role: AgentRole) -> AgentExecutionPort:
    return select_agent_execution(
        db,
        prompt_port=LegacyPromptAssemblyAdapter(db, role, _DEFAULT_GLOBAL_PROMPT),
        knowledge_port=LegacyKnowledgeAugmentationAdapter(db, role),
        usage_authorization=CurrentUsageAuthorizationAdapter(budget_exceeded),
        recorder=SQLAlchemyAgentExecutionRecorder(db, role, record_usage),
        clock=SystemExecutionClock(),
    )


def _request(
    role: AgentRole,
    *,
    task_type: str,
    input_summary: str,
    user_message: str,
    user_id: uuid.UUID | None,
    use_knowledge: bool,
    execution_context: ExecutionContext | None,
) -> AgentExecutionRequest:
    return AgentExecutionRequest(
        expert=snapshot_from_role(role),
        task_type=task_type,
        input_summary=input_summary,
        user_message=user_message,
        user_id=user_id,
        use_knowledge=use_knowledge,
        trace=ExecutionTrace(
            workflow_run_id=(
                execution_context.workflow_run_id if execution_context else None
            ),
            workflow_step_id=(
                execution_context.workflow_step_id if execution_context else None
            ),
            attempt=execution_context.attempt if execution_context else None,
            trace_id=execution_context.trace_id if execution_context else None,
        ),
    )


async def run_agent(
    db: AsyncSession,
    role: AgentRole,
    *,
    task_type: str,
    input_summary: str,
    user_message: str,
    user_id: uuid.UUID | None = None,
    use_knowledge: bool = False,
    execution_context: ExecutionContext | None = None,
) -> AgentTaskRecord:
    """Preserve the legacy ORM-shaped call while delegating execution inward."""
    result = await _application(db, role).execute(
        _request(
            role,
            task_type=task_type,
            input_summary=input_summary,
            user_message=user_message,
            user_id=user_id,
            use_knowledge=use_knowledge,
            execution_context=execution_context,
        )
    )
    if result.execution_id is None:
        raise RuntimeError("Agent execution result was not recorded")
    record = await db.get(AgentTaskRecord, result.execution_id)
    if record is None:
        raise RuntimeError("Agent execution record is unavailable")
    return record


async def run_agent_stream(
    db: AsyncSession,
    role: AgentRole,
    *,
    task_type: str,
    input_summary: str,
    user_message: str,
    user_id: uuid.UUID | None = None,
    use_knowledge: bool = False,
    execution_context: ExecutionContext | None = None,
) -> AsyncIterator[str | AgentTaskRecord]:
    """Preserve token deltas followed by the final persisted ORM record."""
    request = _request(
        role,
        task_type=task_type,
        input_summary=input_summary,
        user_message=user_message,
        user_id=user_id,
        use_knowledge=use_knowledge,
        execution_context=execution_context,
    )
    async for event in _application(db, role).stream(request):
        if event.delta is not None:
            yield event.delta
            continue
        if event.result is None or event.result.execution_id is None:
            continue
        record = await db.get(AgentTaskRecord, event.result.execution_id)
        if record is None:
            raise RuntimeError("Agent execution record is unavailable")
        yield record
