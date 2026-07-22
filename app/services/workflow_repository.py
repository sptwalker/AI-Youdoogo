"""Durable workflow persistence primitives and atomic workflow creation."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.shared_kernel import ResourceNotFound, RuleViolation
from app.models.task import TaskCard
from app.models.workflow import RUN_QUEUED, WorkflowEvent, WorkflowRun, WorkflowStep
from app.services import outbox_service, task_service


class PlanStepLike(Protocol):
    """编排规划步骤的最小输入契约，避免 repository 反向依赖规划器实现。"""

    no: int
    title: str
    skill: str
    instruction: str
    depends_on: list[int]


def _plan_dict(step: PlanStepLike) -> dict[str, Any]:
    return {
        "no": step.no,
        "title": step.title,
        "skill": step.skill,
        "instruction": step.instruction,
        "depends_on": list(step.depends_on),
    }


async def append_event(
    db: AsyncSession,
    run: WorkflowRun,
    event_type: str,
    *,
    step: WorkflowStep | None = None,
    attempt: int | None = None,
    payload: dict[str, Any] | None = None,
) -> WorkflowEvent:
    """追加一条不可变工作流事件。"""
    event = WorkflowEvent(
        workflow_run_id=run.id,
        workflow_step_id=step.id if step else None,
        event_type=event_type,
        attempt=attempt,
        trace_id=run.trace_id,
        payload=payload or {},
    )
    db.add(event)
    await db.flush()
    return event


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
    """在调用方事务中原子创建 workflow、TaskCard 镜像、步骤、事件和首个 outbox。"""
    if len(steps) < 2:
        raise RuleViolation("持久化编排至少需要两个步骤")
    parent = await task_service.create_task(
        db,
        title=title[:200],
        task_type="orchestration",
        creator_id=creator_id,
        assignee_agent_id=assignee_agent_id,
        payload={"origin": "workflow", "request": request},
    )
    run = WorkflowRun(
        parent_task_id=parent.id,
        creator_id=creator_id,
        assignee_agent_id=assignee_agent_id,
        title=title[:200],
        request_text=request,
        status=RUN_QUEUED,
        plan=[_plan_dict(step) for step in steps],
    )
    db.add(run)
    await db.flush()

    by_no: dict[int, tuple[WorkflowStep, TaskCard]] = {}
    for spec in sorted(steps, key=lambda item: item.no):
        red_line = bool(is_red_line(spec.skill))
        card = await task_service.create_task(
            db,
            title=spec.title,
            task_type=spec.skill,
            creator_id=creator_id,
            assignee_agent_id=assignee_agent_id,
            parent_id=parent.id,
            step_no=spec.no,
            payload={
                "instruction": spec.instruction,
                "skill": spec.skill,
                "red_line": red_line,
                "workflow_run_id": str(run.id),
            },
        )
        step = WorkflowStep(
            workflow_run_id=run.id,
            task_card_id=card.id,
            assignee_agent_id=assignee_agent_id,
            step_no=spec.no,
            title=spec.title,
            skill=spec.skill,
            instruction=spec.instruction,
            red_line=red_line,
        )
        db.add(step)
        await db.flush()
        by_no[spec.no] = (step, card)

    for spec in steps:
        step, card = by_no[spec.no]
        step.depends_on = [str(by_no[dep][0].id) for dep in spec.depends_on]
        card.depends_on = [str(by_no[dep][1].id) for dep in spec.depends_on]

    await append_event(db, run, "workflow.created", payload={"step_count": len(steps)})
    await outbox_service.enqueue(
        db,
        aggregate_type="workflow",
        aggregate_id=run.id,
        event_type="workflow.advance",
        dedupe_key=f"workflow:{run.id}:advance:0",
        payload={"workflow_run_id": str(run.id), "trace_id": str(run.trace_id)},
    )
    await db.flush()
    return run


async def get_run(db: AsyncSession, workflow_id: uuid.UUID) -> WorkflowRun:
    run = await db.get(WorkflowRun, workflow_id)
    if run is None or run.is_delete:
        raise ResourceNotFound("工作流不存在")
    return run


async def get_run_by_parent_task(
    db: AsyncSession, parent_task_id: uuid.UUID
) -> WorkflowRun | None:
    return (
        await db.execute(
            select(WorkflowRun).where(
                WorkflowRun.parent_task_id == parent_task_id,
                WorkflowRun.is_delete.is_(False),
            )
        )
    ).scalar_one_or_none()


async def list_steps(db: AsyncSession, workflow_id: uuid.UUID) -> list[WorkflowStep]:
    stmt = (
        select(WorkflowStep)
        .where(
            WorkflowStep.workflow_run_id == workflow_id,
            WorkflowStep.is_delete.is_(False),
        )
        .order_by(WorkflowStep.step_no)
    )
    return list((await db.execute(stmt)).scalars())
