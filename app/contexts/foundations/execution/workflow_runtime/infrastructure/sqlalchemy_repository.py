"""Workflow Runtime persistence and atomic workflow creation."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.execution.workflow_runtime.application.ports import (
    TaskProjectionPort,
)
from app.contexts.foundations.execution.workflow_runtime.contracts.runtime import (
    StartWorkflowCommand,
    StartWorkflowResult,
    WorkflowLaunchStep,
    WorkflowProgressedV1,
    WorkflowRunStatus,
    WorkflowStepStatus,
)
from app.contexts.foundations.execution.workflow_runtime.domain.policies import (
    pair_publish_steps,
    requires_human_review,
)
from app.contexts.foundations.execution.workflow_runtime.infrastructure.events import (
    publish_workflow_progress,
)
from app.contexts.shared_kernel import ResourceNotFound, RuleViolation
from app.core.config import get_settings
from app.models.workflow import (
    RUN_QUEUED,
    RUN_RUNNING,
    RUN_WAITING_HUMAN,
    WorkflowEvent,
    WorkflowRun,
    WorkflowStep,
)
from app.platform.outbox.repository import enqueue, utcnow


@dataclass(frozen=True, slots=True)
class _NewWorkflow:
    run: WorkflowRun
    parent_task_id: uuid.UUID
    occurred_at: datetime


def plan_to_json(steps: tuple[WorkflowLaunchStep, ...]) -> list[dict[str, Any]]:
    return [
        {
            "no": step.number,
            "title": step.title,
            "skill": step.capability_key,
            "instruction": step.instruction,
            "depends_on": list(step.depends_on),
        }
        for step in steps
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


def _new_workflow(command: StartWorkflowCommand) -> _NewWorkflow:
    occurred_at = utcnow()
    run_id = uuid.uuid4()
    parent_task_id = uuid.uuid4()
    trace_id = uuid.uuid4()
    run = WorkflowRun(
        id=run_id,
        parent_task_id=parent_task_id,
        creator_id=command.creator_id,
        assignee_agent_id=command.assignee_expert_id,
        title=(command.title or command.request)[:200],
        request_text=command.request,
        status=RUN_QUEUED,
        trace_id=trace_id,
        plan=plan_to_json(command.steps),
        version=0,
        engine=get_settings().workflow_engine,  # 创建期固定引擎戳（docs/24 §4.4），之后不可改写
    )
    return _NewWorkflow(
        run=run,
        parent_task_id=parent_task_id,
        occurred_at=occurred_at,
    )


def _workflow_created_progress(workflow: _NewWorkflow) -> WorkflowProgressedV1:
    run = workflow.run
    return WorkflowProgressedV1(
        event_id=uuid.uuid4(),
        workflow_id=run.id,
        run_version=0,
        occurred_at=workflow.occurred_at,
        transition="workflow.created",
        run_status=WorkflowRunStatus.QUEUED,
        business_key=str(workflow.parent_task_id),
        payload={
            "parent_task_id": str(workflow.parent_task_id),
            "creator_id": str(run.creator_id),
            "title": run.title,
            "request_text": run.request_text,
            "expert_id": str(run.assignee_agent_id) if run.assignee_agent_id else None,
        },
    )


def _step_created_progress(
    workflow: _NewWorkflow,
    specification: WorkflowLaunchStep,
    step_id: uuid.UUID,
    task_card_id: uuid.UUID,
    depends_on_task_ids: tuple[uuid.UUID, ...],
    red_line: bool,
) -> WorkflowProgressedV1:
    run = workflow.run
    return WorkflowProgressedV1(
        event_id=uuid.uuid4(),
        workflow_id=run.id,
        run_version=0,
        occurred_at=workflow.occurred_at,
        transition="step.created",
        run_status=WorkflowRunStatus.QUEUED,
        step_status=WorkflowStepStatus.QUEUED,
        step_id=step_id,
        step_version=0,
        step_number=specification.number,
        business_key=str(task_card_id),
        payload={
            "parent_task_id": str(workflow.parent_task_id),
            "creator_id": str(run.creator_id),
            "title": run.title,
            "request_text": run.request_text,
            "task_card_id": str(task_card_id),
            "step_title": specification.title,
            "capability_key": specification.capability_key,
            "instruction": specification.instruction,
            "red_line": red_line,
            "expert_id": str(run.assignee_agent_id) if run.assignee_agent_id else None,
            "depends_on_task_ids": [str(item) for item in depends_on_task_ids],
        },
    )


def _new_workflow_step(
    workflow: _NewWorkflow,
    specification: WorkflowLaunchStep,
    step_id: uuid.UUID,
    task_card_id: uuid.UUID,
    step_ids: dict[int, uuid.UUID],
    red_line: bool,
) -> WorkflowStep:
    return WorkflowStep(
        id=step_id,
        workflow_run_id=workflow.run.id,
        task_card_id=task_card_id,
        assignee_agent_id=workflow.run.assignee_agent_id,
        step_no=specification.number,
        title=specification.title,
        skill=specification.capability_key,
        instruction=specification.instruction,
        red_line=red_line,
        depends_on=[str(step_ids[number]) for number in specification.depends_on],
    )


async def _create_steps_and_projections(
    session: AsyncSession,
    task_projection: TaskProjectionPort,
    steps: tuple[WorkflowLaunchStep, ...],
    workflow: _NewWorkflow,
) -> None:
    task_ids = {step.number: uuid.uuid4() for step in steps}
    step_ids = {step.number: uuid.uuid4() for step in steps}
    for specification in sorted(steps, key=lambda item: item.number):
        red_line = requires_human_review(specification.capability_key)
        depends_on_task_ids = tuple(task_ids[number] for number in specification.depends_on)
        await publish_workflow_progress(
            session,
            task_projection,
            _step_created_progress(
                workflow,
                specification,
                step_ids[specification.number],
                task_ids[specification.number],
                depends_on_task_ids,
                red_line,
            ),
        )
        session.add(
            _new_workflow_step(
                workflow,
                specification,
                step_ids[specification.number],
                task_ids[specification.number],
                step_ids,
                red_line,
            )
        )


async def _append_initial_events(
    session: AsyncSession,
    run: WorkflowRun,
    *,
    step_count: int,
) -> None:
    await append_event(session, run, "workflow.created", payload={"step_count": step_count})
    await enqueue(
        session,
        aggregate_type="workflow",
        aggregate_id=run.id,
        event_type="workflow.advance",
        dedupe_key=f"workflow:{run.id}:advance:0",
        payload={"workflow_run_id": str(run.id), "trace_id": str(run.trace_id)},
    )
    await session.flush()


async def create_workflow(
    session: AsyncSession,
    command: StartWorkflowCommand,
    *,
    task_projection: TaskProjectionPort,
) -> WorkflowRun:
    if len(command.steps) < 2:
        raise RuleViolation("持久化编排至少需要两个步骤")
    # 唯一收口：为红线 compose 步配对机械发布步（对规划器/模板不可见），下游一律用配对后的步集。
    command = replace(command, steps=pair_publish_steps(command.steps))
    workflow = _new_workflow(command)
    await publish_workflow_progress(
        session,
        task_projection,
        _workflow_created_progress(workflow),
    )
    session.add(workflow.run)
    await session.flush()
    await _create_steps_and_projections(session, task_projection, command.steps, workflow)
    await session.flush()
    await _append_initial_events(session, workflow.run, step_count=len(command.steps))
    return workflow.run


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


async def count_active_runs_by_engine(session: AsyncSession) -> dict[str, int]:
    """按 engine 统计非终态（queued/running/waiting_human）run 数（docs/24 §4.6）。

    支撑「旧流程 drain 到终态、监控无活动实例后再下线旧 worker」：返回空 dict 即所有引擎已排空。
    只读、不改状态；排空由「停止新建路由到旧引擎 + 旧 run 自然跑到终态」达成，本函数只做可观测。
    """
    statement = (
        select(WorkflowRun.engine, func.count())
        .where(
            WorkflowRun.status.in_((RUN_QUEUED, RUN_RUNNING, RUN_WAITING_HUMAN)),
            WorkflowRun.is_delete.is_(False),
        )
        .group_by(WorkflowRun.engine)
    )
    result = await session.execute(statement)
    return {engine: count for engine, count in result.all()}


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
