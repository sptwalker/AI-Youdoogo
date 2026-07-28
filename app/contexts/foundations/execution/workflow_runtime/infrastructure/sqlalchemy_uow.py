"""SQLAlchemy Workflow Runtime port and Unit of Work implementations."""

from __future__ import annotations

from types import TracebackType
from typing import Self

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.execution.workflow_runtime.application.ports import (
    TaskProjectionPort,
)
from app.contexts.foundations.execution.workflow_runtime.contracts.runtime import (
    ClaimedWorkflowStep,
    ClaimWorkflowStepCommand,
    ClaimWorkflowStepResult,
    FinalizeWorkflowStepCommand,
    FinalizeWorkflowStepResult,
    PreparedWorkflowStep,
    StartWorkflowCommand,
    StartWorkflowResult,
    StepClaimStatus,
    WorkflowStepStatus,
)
from app.contexts.foundations.execution.workflow_runtime.infrastructure import (
    sqlalchemy_repository,
    step_completion,
    step_leases,
)
from app.models.workflow import STEP_FAILED, STEP_RUNNING, STEP_WAITING_HUMAN, WorkflowStep
from app.platform.outbox.repository import enqueue


class SQLAlchemyWorkflowRepository:
    def __init__(
        self,
        session: AsyncSession,
        task_projection: TaskProjectionPort,
    ) -> None:
        self._session = session
        self._task_projection = task_projection

    async def start(self, command: StartWorkflowCommand) -> StartWorkflowResult:
        return sqlalchemy_repository.start_result(
            await sqlalchemy_repository.create_workflow(
                self._session, command, task_projection=self._task_projection
            )
        )

    async def claim(
        self, command: ClaimWorkflowStepCommand
    ) -> ClaimWorkflowStepResult:
        result = await step_leases.claim_step_result(
            self._session,
            command.step_id,
            worker_id=command.worker_id,
            lease_seconds=command.lease_seconds,
            task_projection=self._task_projection,
        )
        if result.status != "claimed" or result.step is None:
            return ClaimWorkflowStepResult(
                StepClaimStatus(result.status), retry_at=result.retry_at
            )
        step = result.step
        if step.lease_until is None or step.lease_owner is None:
            raise RuntimeError("claimed workflow step has no active lease")
        return ClaimWorkflowStepResult(
            StepClaimStatus.CLAIMED,
            ClaimedWorkflowStep(
                workflow_id=step.workflow_run_id,
                step_id=step.id,
                task_card_id=step.task_card_id,
                expert_id=step.assignee_agent_id,
                worker_id=step.lease_owner,
                attempt=step.attempt,
                version=step.version,
                lease_until=step.lease_until,
            ),
        )

    async def prepare(self, claim: ClaimedWorkflowStep) -> PreparedWorkflowStep:
        step = await self._session.get(WorkflowStep, claim.step_id)
        if (
            step is None
            or step.status != STEP_RUNNING
            or step.lease_owner != claim.worker_id
            or step.attempt != claim.attempt
            or step.version != claim.version
        ):
            raise RuntimeError("workflow step claim changed before preparation")
        run = await sqlalchemy_repository.get_run(self._session, claim.workflow_id)
        return PreparedWorkflowStep(
            claim=claim,
            trace_id=run.trace_id,
            creator_id=run.creator_id,
            request_text=run.request_text,
            title=step.title,
            capability_key=step.skill,
            instruction=step.instruction,
            expert=None,
            input_data=tuple((str(key), value) for key, value in (step.input_data or {}).items()),
        )

    async def finalize(
        self, command: FinalizeWorkflowStepCommand
    ) -> FinalizeWorkflowStepResult:
        claim = command.prepared.claim
        step = await self._session.get(WorkflowStep, claim.step_id)
        if step is None:
            return FinalizeWorkflowStepResult(False, claim.workflow_id, claim.step_id)
        datasets = [dict(item) for item in command.execution.datasets]
        artifacts = [dict(item) for item in command.execution.artifacts]
        output_data = {
            "agent_task_record_id": (
                str(command.execution.agent_execution_id)
                if command.execution.agent_execution_id
                else None
            ),
            "datasets": datasets,
            "artifacts": artifacts,
            "tool_execution_ids": [
                str(item) for item in command.execution.capability_execution_ids
            ],
        }
        applied = await step_completion.complete_step(
            self._session,
            step,
            worker_id=claim.worker_id,
            output_data=output_data,
            result_content=command.execution.content,
            succeeded=command.execution.succeeded,
            error=command.execution.error,
            task_projection=self._task_projection,
            expected_version=claim.version,
        )
        if not applied:
            return FinalizeWorkflowStepResult(False, claim.workflow_id, claim.step_id)
        if command.execution.succeeded:
            await step_completion.pipe_outputs(
                self._session,
                step,
                datasets=datasets,
                artifacts=artifacts,
            )
        if step.status not in (STEP_WAITING_HUMAN, STEP_FAILED):
            run = await sqlalchemy_repository.get_run(self._session, claim.workflow_id)
            await enqueue(
                self._session,
                aggregate_type="workflow",
                aggregate_id=run.id,
                event_type="workflow.advance",
                dedupe_key=(
                    f"workflow:{run.id}:advance:{step.id}:attempt:{step.attempt}"
                ),
                payload={"workflow_run_id": str(run.id), "trace_id": str(run.trace_id)},
            )
        return FinalizeWorkflowStepResult(
            True,
            claim.workflow_id,
            claim.step_id,
            WorkflowStepStatus(step.status),
            step.version,
        )


class SQLAlchemyWorkflowUnitOfWork:
    def __init__(
        self,
        session: AsyncSession,
        task_projection: TaskProjectionPort,
    ) -> None:
        self._session = session
        self.workflows = SQLAlchemyWorkflowRepository(session, task_projection)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if exc is not None:
            await self.rollback()

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()


class SQLAlchemyWorkflowUnitOfWorkFactory:
    def __init__(
        self,
        session: AsyncSession,
        task_projection: TaskProjectionPort,
    ) -> None:
        self._session = session
        self._task_projection = task_projection

    def __call__(self) -> SQLAlchemyWorkflowUnitOfWork:
        return SQLAlchemyWorkflowUnitOfWork(self._session, self._task_projection)
