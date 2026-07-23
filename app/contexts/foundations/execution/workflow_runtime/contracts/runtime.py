"""Pure commands, results, and versioned events for durable workflows."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from app.contexts.foundations.execution.work_planning.contracts.planning import WorkflowPlan
from app.contexts.foundations.workforce.expert_management.contracts.execution import (
    ExpertExecutionSnapshot,
)


class WorkflowRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_HUMAN = "waiting_human"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkflowStepStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_HUMAN = "waiting_human"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepClaimStatus(StrEnum):
    CLAIMED = "claimed"
    BUSY = "busy"
    TERMINAL = "terminal"


@dataclass(frozen=True, slots=True)
class StartWorkflowCommand:
    plan: WorkflowPlan


@dataclass(frozen=True, slots=True)
class StartWorkflowResult:
    workflow_id: uuid.UUID
    parent_task_id: uuid.UUID
    trace_id: uuid.UUID
    status: WorkflowRunStatus
    version: int


@dataclass(frozen=True, slots=True)
class ClaimWorkflowStepCommand:
    step_id: uuid.UUID
    worker_id: str
    lease_seconds: int


@dataclass(frozen=True, slots=True)
class ClaimedWorkflowStep:
    workflow_id: uuid.UUID
    step_id: uuid.UUID
    task_card_id: uuid.UUID | None
    expert_id: uuid.UUID | None
    worker_id: str
    attempt: int
    version: int
    lease_until: datetime


@dataclass(frozen=True, slots=True)
class ClaimWorkflowStepResult:
    status: StepClaimStatus
    claim: ClaimedWorkflowStep | None = None
    retry_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class PrepareWorkflowStepCommand:
    claim: ClaimedWorkflowStep


@dataclass(frozen=True, slots=True)
class PreparedWorkflowStep:
    claim: ClaimedWorkflowStep
    trace_id: uuid.UUID
    creator_id: uuid.UUID
    request_text: str
    title: str
    capability_key: str
    instruction: str
    expert: ExpertExecutionSnapshot | None
    input_data: tuple[tuple[str, object], ...] = ()


@dataclass(frozen=True, slots=True)
class ExecuteWorkflowStepResult:
    succeeded: bool
    content: str
    agent_execution_id: uuid.UUID | None = None
    datasets: tuple[tuple[tuple[str, object], ...], ...] = ()
    artifacts: tuple[tuple[tuple[str, object], ...], ...] = ()
    capability_execution_ids: tuple[uuid.UUID, ...] = ()
    error: str | None = None


@dataclass(frozen=True, slots=True)
class FinalizeWorkflowStepCommand:
    prepared: PreparedWorkflowStep
    execution: ExecuteWorkflowStepResult


@dataclass(frozen=True, slots=True)
class FinalizeWorkflowStepResult:
    applied: bool
    workflow_id: uuid.UUID
    step_id: uuid.UUID
    status: WorkflowStepStatus | None = None
    version: int | None = None


@dataclass(frozen=True, slots=True)
class StepExecutionDisposition:
    kind: str
    retry_at: datetime | None = None
    reason: str | None = None
    finalization: FinalizeWorkflowStepResult | None = None

    @classmethod
    def complete(cls) -> StepExecutionDisposition:
        return cls("complete")

    @classmethod
    def defer(cls, retry_at: datetime, *, reason: str) -> StepExecutionDisposition:
        return cls("defer", retry_at=retry_at, reason=reason)


@dataclass(frozen=True, slots=True)
class ResumeWorkflowCommand:
    workflow_id: uuid.UUID
    workflow_step_id: uuid.UUID
    task_id: uuid.UUID
    decision: str
    principal_id: uuid.UUID
    expected_step_version: int
    decision_event_id: uuid.UUID


WORKFLOW_PROGRESSED_V1 = "workflow.progressed.v1"


@dataclass(frozen=True, slots=True)
class WorkflowProgressedV1:
    event_id: uuid.UUID
    workflow_id: uuid.UUID
    run_version: int
    occurred_at: datetime
    transition: str
    parent_task_id: uuid.UUID
    creator_id: uuid.UUID
    title: str
    request_text: str
    run_status: WorkflowRunStatus
    step_status: WorkflowStepStatus | None = None
    step_id: uuid.UUID | None = None
    task_card_id: uuid.UUID | None = None
    step_version: int | None = None
    step_number: int | None = None
    step_title: str | None = None
    capability_key: str | None = None
    instruction: str | None = None
    red_line: bool = False
    expert_id: uuid.UUID | None = None
    depends_on_task_ids: tuple[uuid.UUID, ...] = ()
    result_content: str | None = None
    error: str | None = None
