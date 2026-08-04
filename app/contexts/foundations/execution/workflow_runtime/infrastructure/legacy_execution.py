"""Legacy Agent/skill adapters for the four-phase Workflow step use case."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import replace
from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.contracts import (
    AgentRunner,
    ExecutionContext,
    agent_execution_result,
)
from app.agents.tool_dispatcher import ToolDispatcher
from app.contexts.foundations.execution.agent_execution.contracts.execution import (
    AgentExecutionRequest,
    AgentExecutionResult,
)
from app.contexts.foundations.execution.workflow_runtime.application.ports import (
    ExpertSnapshotPort,
    TaskProjectionPort,
    WorkflowUnitOfWorkFactory,
)
from app.contexts.foundations.execution.workflow_runtime.application.step_execution import (
    ClaimWorkflowStep,
    ExecuteWorkflowStep,
    FinalizeWorkflowStep,
    PrepareWorkflowStep,
    WorkflowStepExecutionApplication,
    render_step_message,
)
from app.contexts.foundations.execution.workflow_runtime.contracts.runtime import (
    ClaimedWorkflowStep,
    ClaimWorkflowStepCommand,
    ExecuteWorkflowStepResult,
    PreparedWorkflowStep,
    StepExecutionDisposition,
)
from app.contexts.foundations.execution.workflow_runtime.infrastructure import (
    step_leases,
)
from app.contexts.foundations.execution.workflow_runtime.infrastructure.sqlalchemy_uow import (
    SQLAlchemyWorkflowUnitOfWorkFactory,
)
from app.contexts.foundations.workforce.expert_management.contracts.execution import (
    ExpertExecutionSnapshot,
)
from app.core.config import get_settings
from app.models.workflow import OutboxEvent
from app.platform.database import async_session_factory


def step_message(step: object) -> str:
    """Compatibility helper retained for tests; canonical rendering accepts prepared values."""
    if isinstance(step, PreparedWorkflowStep):
        return render_step_message(step)
    title = str(getattr(step, "title", ""))
    instruction = str(getattr(step, "instruction", title))
    return (
        f"任务：{title}\n要求：{instruction}"
        "\n\n请完成本步骤；需要数据、咨询或交付时使用已启用技能。"
    )


async def lease_heartbeat(
    stop: asyncio.Event,
    *,
    step_id: uuid.UUID,
    attempt: int,
    worker_id: str,
    lease_seconds: int,
) -> None:
    interval = max(1.0, lease_seconds / 3)
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
            return
        except TimeoutError:
            pass
        async with async_session_factory() as heartbeat_db:
            renewed = await step_leases.renew_step_lease(
                heartbeat_db,
                step_id,
                worker_id=worker_id,
                attempt=attempt,
                lease_seconds=lease_seconds,
            )
            if not renewed:
                await heartbeat_db.rollback()
                return
            await heartbeat_db.commit()


class _LeaseHeartbeat:
    def __init__(self, lease_seconds: int) -> None:
        self._lease_seconds = lease_seconds

    def keep_alive(
        self, claim: ClaimedWorkflowStep
    ) -> AbstractAsyncContextManager[None]:
        @asynccontextmanager
        async def _active() -> AsyncIterator[None]:
            stop = asyncio.Event()
            heartbeat = asyncio.create_task(
                lease_heartbeat(
                    stop,
                    step_id=claim.step_id,
                    attempt=claim.attempt,
                    worker_id=claim.worker_id,
                    lease_seconds=self._lease_seconds,
                ),
                name=f"workflow-step-heartbeat-{claim.step_id}",
            )
            try:
                yield None
            finally:
                stop.set()
                await asyncio.gather(heartbeat, return_exceptions=True)

        return _active()


class _LegacyAgentExecutionAdapter:
    def __init__(self, session: AsyncSession, runner: AgentRunner) -> None:
        self._session = session
        self._runner = runner

    async def execute(self, request: AgentExecutionRequest) -> AgentExecutionResult:
        legacy_result = await self._runner(
            self._session,
            request.expert,
            task_type=request.task_type,
            input_summary=request.input_summary,
            user_message=request.user_message,
            user_id=request.user_id,
            use_knowledge=request.use_knowledge,
            execution_context=ExecutionContext(
                workflow_run_id=request.trace.workflow_run_id,
                workflow_step_id=request.trace.workflow_step_id,
                attempt=request.trace.attempt,
                trace_id=request.trace.trace_id,
                idempotency_prefix=(
                    f"{request.trace.workflow_run_id}:"
                    f"{request.trace.workflow_step_id}:logical"
                ),
                user_id=request.user_id,
                agent_runner=self._runner,
            ),
        )
        return replace(agent_execution_result(legacy_result), trace=request.trace)


class _LegacyCapabilityExecutionAdapter:
    def __init__(self, session: AsyncSession, runner: AgentRunner) -> None:
        self._session = session
        self._runner = runner

    async def execute(
        self,
        prepared: PreparedWorkflowStep,
        agent_result: AgentExecutionResult,
    ) -> ExecuteWorkflowStepResult:
        if prepared.expert is None:
            return ExecuteWorkflowStepResult(False, "步骤无可用执行者", error="步骤无可用执行者")
        expert = cast(ExpertExecutionSnapshot, prepared.expert)
        text = agent_result.content or "（无产出）"
        result = await ToolDispatcher().dispatch_text(
            self._session,
            expert,
            text,
            ExecutionContext(
                workflow_run_id=prepared.claim.workflow_id,
                workflow_step_id=prepared.claim.step_id,
                attempt=prepared.claim.attempt,
                trace_id=prepared.trace_id,
                idempotency_prefix=(
                    f"{prepared.claim.workflow_id}:"
                    f"{prepared.claim.step_id}:logical"
                ),
                user_id=prepared.creator_id,
                user_intent=prepared.request_text,
                agent_runner=self._runner,
            ),
            user_id=prepared.creator_id,
            user_intent=prepared.request_text,
        )
        for consulted, consult_record in result.consult_replies:
            answer = consult_record.output_content or consult_record.error_msg or "（无产出）"
            text += f"\n\n---\n【{consulted.name} 答复】\n{answer}"
        text = result.fold_notes(text)
        return ExecuteWorkflowStepResult(
            succeeded=True,
            content=text,
            agent_execution_id=agent_result.execution_id,
            datasets=tuple(_freeze_mapping(item) for item in result.datasets),
            artifacts=tuple(_freeze_mapping(item) for item in result.artifacts),
            capability_execution_ids=tuple(result.tool_execution_ids),
        )


async def execute_step(
    db: AsyncSession,
    event: OutboxEvent,
    *,
    worker_id: str,
    agent_runner: AgentRunner,
    task_projection: TaskProjectionPort,
    experts: ExpertSnapshotPort,
) -> StepExecutionDisposition:
    raw_step_id = event.payload.get("workflow_step_id")
    if not raw_step_id:
        raise ValueError("workflow.step.execute 缺少 workflow_step_id")
    settings = get_settings()
    units = SQLAlchemyWorkflowUnitOfWorkFactory(db, task_projection)
    typed_units = cast(WorkflowUnitOfWorkFactory, units)
    application = WorkflowStepExecutionApplication(
        claim=ClaimWorkflowStep(typed_units),
        prepare=PrepareWorkflowStep(typed_units, experts),
        execute=ExecuteWorkflowStep(
            _LegacyAgentExecutionAdapter(db, agent_runner),
            _LegacyCapabilityExecutionAdapter(db, agent_runner),
        ),
        finalize=FinalizeWorkflowStep(typed_units),
        heartbeat=_LeaseHeartbeat(settings.workflow_step_lease_seconds),
    )
    return await application.run(
        ClaimWorkflowStepCommand(
            step_id=uuid.UUID(str(raw_step_id)),
            worker_id=worker_id,
            lease_seconds=settings.workflow_step_lease_seconds,
        )
    )


def _freeze_mapping(value: dict[str, object]) -> tuple[tuple[str, object], ...]:
    return tuple((str(key), item) for key, item in value.items())


__all__ = [
    "StepExecutionDisposition",
    "execute_step",
    "lease_heartbeat",
    "step_message",
]
