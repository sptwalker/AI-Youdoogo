"""Workflow Runtime-owned persistence, transaction, and execution ports."""

from __future__ import annotations

import uuid
from contextlib import AbstractAsyncContextManager
from typing import Protocol, Self

from app.contexts.foundations.execution.agent_execution.contracts.execution import (
    AgentExecutionRequest,
    AgentExecutionResult,
)
from app.contexts.foundations.execution.workflow_runtime.contracts.runtime import (
    ClaimedWorkflowStep,
    ClaimWorkflowStepCommand,
    ClaimWorkflowStepResult,
    ExecuteWorkflowStepResult,
    FinalizeWorkflowStepCommand,
    FinalizeWorkflowStepResult,
    PreparedWorkflowStep,
    StartWorkflowCommand,
    StartWorkflowResult,
    WorkflowProgressedV1,
)
from app.contexts.foundations.workforce.expert_management.contracts.execution import (
    ExpertExecutionSnapshot,
)


class WorkflowRepositoryPort(Protocol):
    async def start(self, command: StartWorkflowCommand) -> StartWorkflowResult: ...

    async def claim(
        self, command: ClaimWorkflowStepCommand
    ) -> ClaimWorkflowStepResult: ...

    async def prepare(self, claim: ClaimedWorkflowStep) -> PreparedWorkflowStep: ...

    async def finalize(
        self, command: FinalizeWorkflowStepCommand
    ) -> FinalizeWorkflowStepResult: ...


class WorkflowUnitOfWork(Protocol):
    workflows: WorkflowRepositoryPort

    async def __aenter__(self) -> Self: ...

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


class WorkflowUnitOfWorkFactory(Protocol):
    def __call__(self) -> WorkflowUnitOfWork: ...


class WorkflowEventPublisherPort(Protocol):
    async def publish(self, event: WorkflowProgressedV1) -> None: ...


class TaskProjectionPort(Protocol):
    async def apply(self, event: WorkflowProgressedV1) -> bool: ...


class ExpertSnapshotPort(Protocol):
    async def get_by_id(self, expert_id: uuid.UUID) -> ExpertExecutionSnapshot | None: ...


class WorkflowAgentExecutionPort(Protocol):
    async def execute(self, request: AgentExecutionRequest) -> AgentExecutionResult: ...


class WorkflowCapabilityExecutionPort(Protocol):
    async def execute(
        self,
        prepared: PreparedWorkflowStep,
        agent_result: AgentExecutionResult,
    ) -> ExecuteWorkflowStepResult: ...


class WorkflowLeaseHeartbeatPort(Protocol):
    def keep_alive(self, claim: ClaimedWorkflowStep) -> AbstractAsyncContextManager[None]: ...
