"""Published Agent Execution operations."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.execution.agent_execution.contracts.consult import (
    ConsultExpertCommand,
    ConsultExpertResult,
)
from app.contexts.foundations.execution.agent_execution.contracts.execution import (
    AgentExecutionRequest,
    AgentExecutionResult,
)
from app.contexts.foundations.execution.agent_execution.contracts.records import (
    AgentExecutionRecordView,
)
from app.contexts.foundations.execution.agent_execution.infrastructure.composition import (
    build_agent_execution_application,
    build_agent_execution_records,
    build_consult_expert,
)


async def execute_agent(
    session: AsyncSession,
    request: AgentExecutionRequest,
) -> AgentExecutionResult:
    return await build_agent_execution_application(session).execute(request)


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
