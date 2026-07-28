"""Focused composition helpers for durable Workflow Runtime integration tests."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.business.task_management.infrastructure.sqlalchemy_adapter import (
    SQLAlchemyTaskManagementAdapter,
)
from app.contexts.foundations.execution.work_planning.contracts.planning import (
    WorkflowPlan,
    WorkflowPlanStep,
    WorkIntent,
)
from app.contexts.foundations.execution.workflow_runtime.application.planning_translation import (
    planning_to_start_command,
)
from app.contexts.foundations.execution.workflow_runtime.domain.policies import (
    requires_human_review,
)
from app.contexts.foundations.execution.workflow_runtime.infrastructure import (
    human_decisions,
    sqlalchemy_repository,
    step_completion,
    step_leases,
)
from app.models.task import TaskCard
from app.models.workflow import WorkflowRun, WorkflowStep


@dataclass
class PlanStep:
    no: int
    title: str
    skill: str
    instruction: str
    depends_on: list[int] = field(default_factory=list)


def is_red_line(skill: str) -> bool:
    return requires_human_review(skill)


def _projection(session: AsyncSession) -> SQLAlchemyTaskManagementAdapter:
    return SQLAlchemyTaskManagementAdapter(session)


async def create_workflow(
    session: AsyncSession,
    *,
    request: str,
    title: str,
    creator_id: uuid.UUID,
    assignee_agent_id: uuid.UUID | None,
    steps: Sequence[PlanStep],
    is_red_line: Callable[[str], bool],
) -> WorkflowRun:
    del is_red_line
    plan = WorkflowPlan(
        intent=WorkIntent(
            request=request,
            creator_id=creator_id,
            title=title,
            assignee_expert_id=assignee_agent_id,
        ),
        steps=tuple(
            WorkflowPlanStep(
                number=step.no,
                title=step.title,
                capability_key=step.skill,
                instruction=step.instruction,
                depends_on=tuple(step.depends_on),
            )
            for step in steps
        ),
    )
    return await sqlalchemy_repository.create_workflow(
        session,
        planning_to_start_command(plan),
        task_projection=_projection(session),
    )


async def list_steps(session: AsyncSession, workflow_id: uuid.UUID) -> list[WorkflowStep]:
    return await sqlalchemy_repository.list_steps(session, workflow_id)


async def claim_step(
    session: AsyncSession,
    step_id: uuid.UUID,
    *,
    worker_id: str,
    lease_seconds: int,
) -> WorkflowStep | None:
    return await step_leases.claim_step(
        session,
        step_id,
        worker_id=worker_id,
        lease_seconds=lease_seconds,
        task_projection=_projection(session),
    )


async def claim_step_result(
    session: AsyncSession,
    step_id: uuid.UUID,
    *,
    worker_id: str,
    lease_seconds: int,
) -> step_leases.StepClaimResult:
    return await step_leases.claim_step_result(
        session,
        step_id,
        worker_id=worker_id,
        lease_seconds=lease_seconds,
        task_projection=_projection(session),
    )


async def complete_step(
    session: AsyncSession,
    step: WorkflowStep,
    *,
    worker_id: str,
    output_data: dict[str, Any],
    result_content: str,
    succeeded: bool,
    error: str | None = None,
) -> bool:
    return await step_completion.complete_step(
        session,
        step,
        worker_id=worker_id,
        output_data=output_data,
        result_content=result_content,
        succeeded=succeeded,
        error=error,
        task_projection=_projection(session),
    )


async def apply_task_decision(session: AsyncSession, event: Any) -> WorkflowRun | None:
    return await human_decisions.apply_task_decision(
        session,
        event,
        task_projection=_projection(session),
    )


async def accept_human_step(
    session: AsyncSession,
    task_card_id: uuid.UUID,
    *,
    operator_id: uuid.UUID | None,
) -> WorkflowRun | None:
    return await human_decisions.accept_human_step(
        session,
        task_card_id,
        operator_id=operator_id,
        task_projection=_projection(session),
    )


async def get_task(session: AsyncSession, task_id: uuid.UUID) -> TaskCard:
    return await _projection(session).get_record(task_id)


async def transition(
    session: AsyncSession,
    task_id: uuid.UUID,
    to_status: str,
    *,
    operator_id: uuid.UUID | None,
    note: str | None = None,
    result_content: str | None = None,
) -> TaskCard:
    return await _projection(session).transition_record(
        task_id,
        to_status,
        operator_id=operator_id,
        note=note,
        result_content=result_content,
    )
