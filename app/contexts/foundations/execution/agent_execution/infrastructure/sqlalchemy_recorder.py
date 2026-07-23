"""Persist Agent execution evidence and usage using the existing schema."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.execution.agent_execution.application.use_cases import (
    llm_role_for,
)
from app.contexts.foundations.execution.agent_execution.contracts.execution import (
    AgentExecutionRequest,
    AgentExecutionResult,
)
from app.models.agent import AgentRole, AgentTaskRecord


class SQLAlchemyAgentExecutionRecorder:
    """Own translation between pure results and AgentTaskRecord/LlmCallLog rows."""

    def __init__(
        self,
        session: AsyncSession,
        role_record: AgentRole | None,
        usage_recorder: Callable[..., Any],
    ) -> None:
        self._session = session
        self._role = role_record
        self._usage_recorder = usage_recorder

    async def record(
        self, request: AgentExecutionRequest, result: AgentExecutionResult
    ) -> AgentExecutionResult:
        record = AgentTaskRecord(
            agent_role_id=request.expert.expert_id,
            task_type=request.task_type,
            input_summary=request.input_summary,
            output_content=result.content,
            tools_called=[
                {
                    "capability_key": activity.capability_key,
                    "status": activity.status,
                    "invocation_id": (
                        str(activity.invocation_id) if activity.invocation_id else None
                    ),
                }
                for activity in result.capability_activity
            ],
            model_used=result.model,
            status=result.status.value,
            error_msg=result.error.message if result.error else None,
            duration_ms=result.duration_ms,
            sources=[
                {
                    "file_id": source.file_id,
                    "file_name": source.file_name,
                    "chunk_index": source.chunk_index,
                }
                for source in result.sources
            ],
            workflow_run_id=request.trace.workflow_run_id,
            workflow_step_id=request.trace.workflow_step_id,
            attempt_no=request.trace.attempt,
            trace_id=request.trace.trace_id,
        )
        self._session.add(record)
        await self._session.commit()
        await self._session.refresh(record)
        await self._usage_recorder(
            self._session,
            role=llm_role_for(request.expert.model_role),
            model=result.model,
            prompt_tokens=result.usage.prompt_tokens,
            completion_tokens=result.usage.completion_tokens,
            total_tokens=result.usage.total_tokens,
            duration_ms=result.duration_ms,
            status=result.status.value,
            task_id=record.id,
            user_id=request.user_id,
            department_id=request.expert.department_id,
            workflow_run_id=request.trace.workflow_run_id,
            workflow_step_id=request.trace.workflow_step_id,
            attempt_no=request.trace.attempt,
            trace_id=request.trace.trace_id,
        )
        return replace(result, execution_id=record.id)
