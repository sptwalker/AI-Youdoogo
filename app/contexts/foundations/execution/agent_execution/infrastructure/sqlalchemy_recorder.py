"""Persist Agent execution evidence and usage using the existing schema."""

from __future__ import annotations

import uuid
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
    AgentExecutionStatus,
)
from app.contexts.foundations.knowledge.knowledge_indexing.public import (
    enqueue_personal_knowledge_sink,
)
from app.core.config import get_settings
from app.models.agent import AgentTaskRecord


class SQLAlchemyAgentExecutionRecorder:
    """Own translation between pure results and AgentTaskRecord/LlmCallLog rows."""

    def __init__(
        self,
        session: AsyncSession,
        _legacy_role_record: object | None,
        usage_recorder: Callable[..., Any],
    ) -> None:
        self._session = session
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
        await self._session.flush()
        await self._maybe_sink_personal_knowledge(request, result, record.id)
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

    async def _maybe_sink_personal_knowledge(
        self,
        request: AgentExecutionRequest,
        result: AgentExecutionResult,
        record_id: uuid.UUID,
    ) -> None:
        """直连 AI 产出（非工作流子步）成功且有正文 → 登记自动沉淀（docs/27 B1.3）。

        默认关（personal_knowledge_autosink_enabled）；工作流子步（有 workflow_step_id）不沉淀，
        只沉淀面向真人的直连产出，避免中间步噪声。红线：内部辅助执行，不外发。
        """
        if not get_settings().personal_knowledge_autosink_enabled:
            return
        content = (result.content or "").strip()
        if (
            request.trace.workflow_step_id is not None
            or request.user_id is None
            or result.status != AgentExecutionStatus.SUCCEEDED
            or not content
        ):
            return
        await enqueue_personal_knowledge_sink(
            self._session,
            owner_user_id=request.user_id,
            title=request.input_summary or "AI 产出",
            content=content,
            source_record_id=record_id,
        )
