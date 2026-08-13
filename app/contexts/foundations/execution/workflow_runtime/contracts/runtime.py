"""Pure commands, results, and versioned events for durable workflows."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


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
class WorkflowLaunchStep:
    """Runtime-owned step spec: opaque to product concepts, decoded from the caller's plan.

    字段名对齐 ``work_planning`` 的 ``WorkflowPlanStep``，但由运行时契约自持——
    切断契约对 ``work_planning`` 的具名依赖（[[ADR 0007]]）。
    """

    number: int
    title: str
    capability_key: str
    instruction: str
    depends_on: tuple[int, ...] = ()
    # 逐步承接专家（P3-2）：缺省 None → 回落 run 的单一 assignee，不破坏既有单派发。
    assignee_expert_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class StartWorkflowCommand:
    creator_id: uuid.UUID
    request: str
    steps: tuple[WorkflowLaunchStep, ...]
    title: str | None = None
    assignee_expert_id: uuid.UUID | None = None


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
    expert: object | None
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


WORKFLOW_PROGRESSED_V1 = "workflow.progressed.v1"


@dataclass(frozen=True, slots=True)
class WorkflowProgressedV1:
    """Runtime-generic progress event.

    产品字段不再具名于运行时契约：路由键 ``business_key`` 与产品负载 ``payload`` 均不透明，
    由消费方 Context 的 ACL 解码（task_management：``workflow_event_acl``）。
    ``payload`` 值一律 JSON 安全（uuid→str），保证 outbox 往返无损。
    """

    event_id: uuid.UUID
    workflow_id: uuid.UUID
    run_version: int
    occurred_at: datetime
    transition: str
    run_status: WorkflowRunStatus
    business_key: str
    payload: Mapping[str, object]
    step_status: WorkflowStepStatus | None = None
    step_id: uuid.UUID | None = None
    step_version: int | None = None
    step_number: int | None = None
    error: str | None = None
