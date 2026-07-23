"""One-way compatibility facade for Workflow Runtime persistence."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.business.task_management.infrastructure.sqlalchemy_adapter import (
    SQLAlchemyTaskManagementAdapter,
)
from app.contexts.foundations.execution.work_planning.contracts.planning import (
    WorkflowPlan,
    WorkflowPlanStep,
    WorkIntent,
)
from app.contexts.foundations.execution.workflow_runtime.contracts.runtime import (
    StartWorkflowCommand,
)
from app.contexts.foundations.execution.workflow_runtime.infrastructure import (
    sqlalchemy_repository,
)
from app.models.workflow import WorkflowRun


class PlanStepLike(Protocol):
    no: int
    title: str
    skill: str
    instruction: str
    depends_on: list[int]


async def create_workflow(
    db: AsyncSession,
    *,
    request: str,
    title: str,
    creator_id: uuid.UUID,
    assignee_agent_id: uuid.UUID | None,
    steps: Sequence[PlanStepLike],
    is_red_line: Callable[[str], bool],
) -> WorkflowRun:
    del is_red_line
    known = {step.no for step in steps}
    for step in steps:
        for dependency in step.depends_on:
            if dependency not in known:
                raise KeyError(dependency)
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
        db,
        StartWorkflowCommand(plan),
        task_projection=SQLAlchemyTaskManagementAdapter(db),
    )


append_event = sqlalchemy_repository.append_event
get_run = sqlalchemy_repository.get_run
get_run_by_parent_task = sqlalchemy_repository.get_run_by_parent_task
list_steps = sqlalchemy_repository.list_steps


__all__ = [
    "PlanStepLike",
    "append_event",
    "create_workflow",
    "get_run",
    "get_run_by_parent_task",
    "list_steps",
]
