"""One-way compatibility facade for Workflow Runtime state transitions."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.business.task_management.contracts.tasks import TaskDecisionRecordedV1
from app.contexts.business.task_management.infrastructure.sqlalchemy_adapter import (
    SQLAlchemyTaskManagementAdapter,
)
from app.contexts.foundations.execution.workflow_runtime.infrastructure.sqlalchemy_state import (
    StepClaimResult,
    pipe_outputs,
    ready_steps,
    renew_step_lease,
)
from app.contexts.foundations.execution.workflow_runtime.infrastructure.sqlalchemy_state import (
    accept_human_step as _accept_human_step,
)
from app.contexts.foundations.execution.workflow_runtime.infrastructure.sqlalchemy_state import (
    apply_task_decision as _apply_task_decision,
)
from app.contexts.foundations.execution.workflow_runtime.infrastructure.sqlalchemy_state import (
    claim_step as _claim_step,
)
from app.contexts.foundations.execution.workflow_runtime.infrastructure.sqlalchemy_state import (
    claim_step_result as _claim_step_result,
)
from app.contexts.foundations.execution.workflow_runtime.infrastructure.sqlalchemy_state import (
    complete_step as _complete_step,
)
from app.contexts.foundations.execution.workflow_runtime.infrastructure.sqlalchemy_state import (
    fail_from_outbox as _fail_from_outbox,
)
from app.models.workflow import WorkflowRun, WorkflowStep


def _projection(db: AsyncSession) -> SQLAlchemyTaskManagementAdapter:
    return SQLAlchemyTaskManagementAdapter(db)


async def claim_step_result(
    db: AsyncSession,
    step_id: uuid.UUID,
    *,
    worker_id: str,
    lease_seconds: int,
) -> StepClaimResult:
    return await _claim_step_result(
        db,
        step_id,
        worker_id=worker_id,
        lease_seconds=lease_seconds,
        task_projection=_projection(db),
    )


async def claim_step(
    db: AsyncSession,
    step_id: uuid.UUID,
    *,
    worker_id: str,
    lease_seconds: int,
) -> WorkflowStep | None:
    return await _claim_step(
        db,
        step_id,
        worker_id=worker_id,
        lease_seconds=lease_seconds,
        task_projection=_projection(db),
    )


async def complete_step(
    db: AsyncSession,
    step: WorkflowStep,
    *,
    worker_id: str,
    output_data: dict[str, Any],
    result_content: str,
    succeeded: bool,
    error: str | None = None,
) -> bool:
    return await _complete_step(
        db,
        step,
        worker_id=worker_id,
        output_data=output_data,
        result_content=result_content,
        succeeded=succeeded,
        error=error,
        task_projection=_projection(db),
    )


async def accept_human_step(
    db: AsyncSession,
    task_card_id: uuid.UUID,
    *,
    operator_id: uuid.UUID | None,
) -> WorkflowRun | None:
    return await _accept_human_step(
        db,
        task_card_id,
        operator_id=operator_id,
        task_projection=_projection(db),
    )


async def apply_task_decision(
    db: AsyncSession, event: TaskDecisionRecordedV1
) -> WorkflowRun | None:
    return await _apply_task_decision(db, event, task_projection=_projection(db))


async def fail_from_outbox(
    db: AsyncSession,
    event: Any,
    *,
    error: str,
) -> WorkflowRun | None:
    return await _fail_from_outbox(
        db, event, error=error, task_projection=_projection(db)
    )


__all__ = [
    "StepClaimResult",
    "accept_human_step",
    "apply_task_decision",
    "claim_step",
    "claim_step_result",
    "complete_step",
    "fail_from_outbox",
    "pipe_outputs",
    "ready_steps",
    "renew_step_lease",
]
