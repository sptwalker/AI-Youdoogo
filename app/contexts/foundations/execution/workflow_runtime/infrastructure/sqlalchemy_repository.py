"""Workflow Runtime persistence and atomic workflow creation."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.execution.work_planning.contracts.planning import (
    WorkflowPlan,
)
from app.contexts.foundations.execution.workflow_runtime.application.ports import (
    TaskProjectionPort,
)
from app.contexts.foundations.execution.workflow_runtime.contracts.runtime import (
    StartWorkflowCommand,
    StartWorkflowResult,
    WorkflowProgressedV1,
    WorkflowRunStatus,
    WorkflowStepStatus,
)
from app.contexts.foundations.execution.workflow_runtime.domain.policies import (
    requires_human_review,
)
from app.contexts.foundations.execution.workflow_runtime.infrastructure.events import (
    publish_workflow_progress,
)
from app.contexts.shared_kernel import ResourceNotFound, RuleViolation
from app.models.workflow import RUN_QUEUED, WorkflowEvent, WorkflowRun, WorkflowStep
from app.platform.outbox.repository import enqueue, utcnow


def plan_to_json(plan: WorkflowPlan) -> list[dict[str, Any]]:
    return [
        {
            "no": step.number,
            "title": step.title,
            "skill": step.capability_key,
            "instruction": step.instruction,
            "depends_on": list(step.depends_on),
        }
        for step in plan.steps
    ]


async def append_event(
    session: AsyncSession,
    run: WorkflowRun,
    event_type: str,
    *,
    step: WorkflowStep | None = None,
    attempt: int | None = None,
    payload: dict[str, Any] | None = None,
) -> WorkflowEvent:
    event = WorkflowEvent(
        workflow_run_id=run.id,
        workflow_step_id=step.id if step else None,
        event_type=event_type,
        attempt=attempt,
        trace_id=run.trace_id,
        payload=payload or {},
    )
    session.add(event)
    await session.flush()
    return event


async def create_workflow(
    session: AsyncSession,
    command: StartWorkflowCommand,
    *,
    task_projection: TaskProjectionPort,
) -> WorkflowRun:
    plan = command.plan
    if len(plan.steps) < 2:
        raise RuleViolation("持久化编排至少需要两个步骤")
    intent = plan.intent
    now = utcnow()
    run_id = uuid.uuid4()
    parent_task_id = uuid.uuid4()
    trace_id = uuid.uuid4()
    run = WorkflowRun(
        id=run_id,
        parent_task_id=parent_task_id,
        creator_id=intent.creator_id,
        assignee_agent_id=intent.assignee_expert_id,
        title=(intent.title or intent.request)[:200],
        request_text=intent.request,
        status=RUN_QUEUED,
        trace_id=trace_id,
        plan=plan_to_json(plan),
        version=0,
    )
    await publish_workflow_progress(
        session,
        task_projection,
        WorkflowProgressedV1(
            event_id=uuid.uuid4(),
            workflow_id=run_id,
            run_version=0,
            occurred_at=now,
            transition="workflow.created",
            parent_task_id=parent_task_id,
            creator_id=intent.creator_id,
            title=run.title,
            request_text=intent.request,
            run_status=WorkflowRunStatus.QUEUED,
            expert_id=intent.assignee_expert_id,
        ),
    )
    session.add(run)
    await session.flush()

    by_number: dict[int, WorkflowStep] = {}
    task_ids = {step.number: uuid.uuid4() for step in plan.steps}
    step_ids = {step.number: uuid.uuid4() for step in plan.steps}
    for specification in sorted(plan.steps, key=lambda item: item.number):
        red_line = requires_human_review(specification.capability_key)
        depends_on_task_ids = tuple(task_ids[number] for number in specification.depends_on)
        await publish_workflow_progress(
            session,
            task_projection,
            WorkflowProgressedV1(
                event_id=uuid.uuid4(),
                workflow_id=run_id,
                run_version=0,
                occurred_at=now,
                transition="step.created",
                parent_task_id=parent_task_id,
                creator_id=intent.creator_id,
                title=run.title,
                request_text=intent.request,
                run_status=WorkflowRunStatus.QUEUED,
                step_status=WorkflowStepStatus.QUEUED,
                step_id=step_ids[specification.number],
                task_card_id=task_ids[specification.number],
                step_version=0,
                step_number=specification.number,
                step_title=specification.title,
                capability_key=specification.capability_key,
                instruction=specification.instruction,
                red_line=red_line,
                expert_id=intent.assignee_expert_id,
                depends_on_task_ids=depends_on_task_ids,
            ),
        )
        step = WorkflowStep(
            id=step_ids[specification.number],
            workflow_run_id=run_id,
            task_card_id=task_ids[specification.number],
            assignee_agent_id=intent.assignee_expert_id,
            step_no=specification.number,
            title=specification.title,
            skill=specification.capability_key,
            instruction=specification.instruction,
            red_line=red_line,
            depends_on=[str(step_ids[number]) for number in specification.depends_on],
        )
        session.add(step)
        by_number[specification.number] = step
    await session.flush()
    await append_event(session, run, "workflow.created", payload={"step_count": len(plan.steps)})
    await enqueue(
        session,
        aggregate_type="workflow",
        aggregate_id=run.id,
        event_type="workflow.advance",
        dedupe_key=f"workflow:{run.id}:advance:0",
        payload={"workflow_run_id": str(run.id), "trace_id": str(run.trace_id)},
    )
    await session.flush()
    return run


async def get_run(session: AsyncSession, workflow_id: uuid.UUID) -> WorkflowRun:
    run = await session.get(WorkflowRun, workflow_id)
    if run is None or run.is_delete:
        raise ResourceNotFound("工作流不存在")
    return run


async def get_run_by_parent_task(
    session: AsyncSession, parent_task_id: uuid.UUID
) -> WorkflowRun | None:
    return (
        await session.execute(
            select(WorkflowRun).where(
                WorkflowRun.parent_task_id == parent_task_id,
                WorkflowRun.is_delete.is_(False),
            )
        )
    ).scalar_one_or_none()


async def list_steps(session: AsyncSession, workflow_id: uuid.UUID) -> list[WorkflowStep]:
    statement = (
        select(WorkflowStep)
        .where(
            WorkflowStep.workflow_run_id == workflow_id,
            WorkflowStep.is_delete.is_(False),
        )
        .order_by(WorkflowStep.step_no)
    )
    return list((await session.execute(statement)).scalars())


def start_result(run: WorkflowRun) -> StartWorkflowResult:
    if run.parent_task_id is None:
        raise RuntimeError("workflow parent task projection is missing")
    return StartWorkflowResult(
        workflow_id=run.id,
        parent_task_id=run.parent_task_id,
        trace_id=run.trace_id,
        status=WorkflowRunStatus(run.status),
        version=run.version,
    )
