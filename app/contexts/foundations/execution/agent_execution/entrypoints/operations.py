"""Published Agent Execution operations."""

import json
import uuid
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.contracts import ExecutionContext
from app.contexts.foundations.execution.agent_execution.contracts.consult import (
    ConsultExpertCommand,
    ConsultExpertResult,
)
from app.contexts.foundations.execution.agent_execution.contracts.execution import (
    AgentExecutionRequest,
    AgentExecutionResult,
    AgentExecutionStreamEvent,
    ExecutionTrace,
)
from app.contexts.foundations.execution.agent_execution.contracts.records import (
    AgentExecutionRecordView,
)
from app.contexts.foundations.execution.agent_execution.infrastructure.composition import (
    build_agent_execution_application,
    build_agent_execution_records,
    build_consult_expert,
)
from app.contexts.foundations.workforce.expert_management.contracts.execution import (
    ExpertExecutionSnapshot,
)
from app.models.agent import AgentRole, AgentTaskRecord


async def execute_agent(
    session: AsyncSession,
    request: AgentExecutionRequest,
) -> AgentExecutionResult:
    return await build_agent_execution_application(session).execute(request)


def stream_agent(
    session: AsyncSession,
    request: AgentExecutionRequest,
    *,
    release_before_external_call: bool = False,
) -> AsyncIterator[AgentExecutionStreamEvent]:
    """Stream one execution without exposing ORM records to the caller."""
    return build_agent_execution_application(
        session,
        release_before_external_call=release_before_external_call,
    ).stream(request)


async def consult_expert(
    session: AsyncSession,
    command: ConsultExpertCommand,
) -> ConsultExpertResult:
    return await build_consult_expert(session).execute(command)


async def get_execution_record(
    session: AsyncSession,
    execution_id: uuid.UUID,
) -> AgentExecutionRecordView | None:
    return await build_agent_execution_records(session).get(execution_id)


async def list_execution_records(
    session: AsyncSession,
    limit: int,
) -> tuple[AgentExecutionRecordView, ...]:
    return await build_agent_execution_records(session).list_recent(limit)


def _orm_request(
    role: AgentRole,
    *,
    task_type: str,
    input_summary: str,
    user_message: str,
    user_id: uuid.UUID | None,
    use_knowledge: bool,
    execution_context: ExecutionContext | None,
) -> AgentExecutionRequest:
    """Translate the current ORM caller contract at the Agent Execution boundary."""
    return AgentExecutionRequest(
        expert=_execution_snapshot_from_legacy_role(role),
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


def _execution_snapshot_from_legacy_role(role: AgentRole) -> ExpertExecutionSnapshot:
    """Translate the explicit legacy ORM entrypoint input into pure execution data."""
    raw_tools = role.tools if isinstance(role.tools, list) else []
    raw_permissions = role.permission_scope if isinstance(role.permission_scope, dict) else {}
    return ExpertExecutionSnapshot(
        expert_id=role.id,
        version=(
            role.update_time.isoformat()
            if role.update_time is not None
            else f"unpersisted:{role.id}"
        ),
        name=role.name,
        title=role.title or "",
        department_id=role.department_id,
        prompt_template=role.prompt_template,
        model_role=role.model_role,
        capability_keys=tuple(item for item in raw_tools if isinstance(item, str)),
        permission_entries=tuple(
            (str(key), value if isinstance(value, str) else json.dumps(
                value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ))
            for key, value in sorted(raw_permissions.items(), key=lambda item: str(item[0]))
        ),
        owner_user_id=role.owner_user_id,
    )


async def run_agent_snapshot(
    db: AsyncSession,
    expert: ExpertExecutionSnapshot,
    *,
    task_type: str,
    input_summary: str,
    user_message: str,
    user_id: uuid.UUID | None = None,
    use_knowledge: bool = False,
    execution_context: ExecutionContext | None = None,
    release_before_external_call: bool = False,
) -> AgentExecutionResult:
    """Compatibility-shaped runner backed by the pure execution request contract."""
    return await build_agent_execution_application(
        db,
        release_before_external_call=release_before_external_call,
    ).execute(
        AgentExecutionRequest(
            expert=expert,
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
    release_before_external_call: bool = False,
) -> AgentTaskRecord:
    """Run one expert and return its persisted ORM record for current adapters."""
    result = await build_agent_execution_application(
        db,
        release_before_external_call=release_before_external_call,
    ).execute(
        _orm_request(
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
    release_before_external_call: bool = False,
) -> AsyncIterator[str | AgentTaskRecord]:
    """Yield token deltas followed by the final persisted ORM record."""
    request = _orm_request(
        role,
        task_type=task_type,
        input_summary=input_summary,
        user_message=user_message,
        user_id=user_id,
        use_knowledge=use_knowledge,
        execution_context=execution_context,
    )
    async for event in build_agent_execution_application(
        db,
        release_before_external_call=release_before_external_call,
    ).stream(request):
        if event.delta is not None:
            yield event.delta
            continue
        if event.result is None or event.result.execution_id is None:
            continue
        record = await db.get(AgentTaskRecord, event.result.execution_id)
        if record is None:
            raise RuntimeError("Agent execution record is unavailable")
        yield record
