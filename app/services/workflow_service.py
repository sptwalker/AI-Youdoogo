"""持久化工作流 repository/use case：原子建流、租约抢占、事件与进度聚合。"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from typing import Any, Protocol

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.models.task import TaskCard
from app.models.workflow import (
    RUN_CANCELLED,
    RUN_FAILED,
    RUN_QUEUED,
    RUN_RUNNING,
    RUN_SUCCEEDED,
    RUN_WAITING_HUMAN,
    STEP_CANCELLED,
    STEP_FAILED,
    STEP_QUEUED,
    STEP_RUNNING,
    STEP_SUCCEEDED,
    STEP_WAITING_HUMAN,
    WorkflowEvent,
    WorkflowRun,
    WorkflowStep,
)
from app.services import outbox_service, task_flow, task_service


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
        raise AppError("持久化编排至少需要两个步骤")
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
        plan=[_plan_dict(s) for s in steps],
    )
    db.add(run)
    await db.flush()

    by_no: dict[int, tuple[WorkflowStep, TaskCard]] = {}
    for spec in sorted(steps, key=lambda item: item.no):
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
                "red_line": bool(is_red_line(spec.skill)),
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
            red_line=bool(is_red_line(spec.skill)),
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
        raise AppError("工作流不存在", code=404, status_code=404)
    return run


async def get_run_by_parent_task(db: AsyncSession, parent_task_id: uuid.UUID) -> WorkflowRun | None:
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


def ready_steps(steps: Sequence[WorkflowStep]) -> list[WorkflowStep]:
    """返回 queued 或租约过期 running 且依赖已成功的步骤。"""
    now = outbox_service.utcnow()
    succeeded = {str(step.id) for step in steps if step.status == STEP_SUCCEEDED}
    ready: list[WorkflowStep] = []
    for step in steps:
        expired = step.status == STEP_RUNNING and _before(step.lease_until, now)
        if step.status != STEP_QUEUED and not expired:
            continue
        if all(dep in succeeded for dep in (step.depends_on or [])):
            ready.append(step)
    return ready


def _before(value: datetime | None, now: datetime) -> bool:
    """SQLite 返回 naive datetime，统一转成与 now 相同的比较口径。"""
    if value is None:
        return False
    if value.tzinfo is None and now.tzinfo is not None:
        value = value.replace(tzinfo=now.tzinfo)
    return value < now


async def claim_step(
    db: AsyncSession,
    step_id: uuid.UUID,
    *,
    worker_id: str,
    lease_seconds: int,
) -> WorkflowStep | None:
    """用 version CAS 抢占步骤；重复 worker 只有一个更新成功。"""
    step = await db.get(WorkflowStep, step_id)
    if step is None or step.is_delete:
        return None
    now = outbox_service.utcnow()
    expired = step.status == STEP_RUNNING and _before(step.lease_until, now)
    if step.status != STEP_QUEUED and not expired:
        return None
    expected = step.version
    prior_owner = step.lease_owner
    result = await db.execute(
        update(WorkflowStep)
        .where(
            WorkflowStep.id == step.id,
            WorkflowStep.version == expected,
            or_(
                WorkflowStep.status == STEP_QUEUED,
                (WorkflowStep.status == STEP_RUNNING) & (WorkflowStep.lease_until < now),
            ),
        )
        .values(
            status=STEP_RUNNING,
            version=expected + 1,
            attempt=WorkflowStep.attempt + 1,
            lease_owner=worker_id,
            lease_until=now + timedelta(seconds=lease_seconds),
            started_at=now,
            completed_at=None,
            last_error=None,
        )
        .execution_options(synchronize_session=False)
    )
    if getattr(result, "rowcount", 0) != 1:
        return None
    await db.flush()
    await db.refresh(step)
    run = await get_run(db, step.workflow_run_id)
    if run.status == RUN_QUEUED:
        run.status = RUN_RUNNING
        run.started_at = now
        run.version += 1
    await _mirror_step_running(db, step)
    await append_event(
        db,
        run,
        "step.reclaimed" if expired else "step.claimed",
        step=step,
        attempt=step.attempt,
        payload={"prior_lease_owner": prior_owner} if expired else {},
    )
    return step


async def renew_step_lease(
    db: AsyncSession,
    step_id: uuid.UUID,
    *,
    worker_id: str,
    attempt: int,
    lease_seconds: int,
) -> bool:
    """当前租约持有者为长调用续租；过期 attempt/其他 worker 不可续租。"""
    now = outbox_service.utcnow()
    result = await db.execute(
        update(WorkflowStep)
        .where(
            WorkflowStep.id == step_id,
            WorkflowStep.status == STEP_RUNNING,
            WorkflowStep.lease_owner == worker_id,
            WorkflowStep.attempt == attempt,
            WorkflowStep.lease_until >= now,
        )
        .values(lease_until=now + timedelta(seconds=lease_seconds))
        .execution_options(synchronize_session=False)
    )
    await db.flush()
    return getattr(result, "rowcount", 0) == 1


async def _mirror_step_running(db: AsyncSession, step: WorkflowStep) -> None:
    if step.task_card_id is None:
        return
    card = await task_service.get_task(db, step.task_card_id)
    if card.status == task_flow.CREATED:
        await task_service.transition(
            db, card.id, task_flow.DISPATCHED, operator_id=None, note="workflow worker 分发"
        )
    if card.status == task_flow.DISPATCHED:
        await task_service.transition(
            db, card.id, task_flow.EXECUTING, operator_id=None, note="workflow worker 执行"
        )


async def _mirror_step_result(
    db: AsyncSession,
    step: WorkflowStep,
    *,
    result_content: str,
    succeeded: bool,
) -> None:
    if step.task_card_id is None:
        return
    card = await task_service.get_task(db, step.task_card_id)
    if card.status == task_flow.EXECUTING:
        await task_service.transition(
            db,
            card.id,
            task_flow.REPORTED,
            operator_id=step.assignee_agent_id,
            note="workflow step 完成" if succeeded else "workflow step 失败",
            result_content=result_content,
        )
    if succeeded and not step.red_line and card.status == task_flow.REPORTED:
        await task_service.transition(
            db, card.id, task_flow.ACCEPTED, operator_id=None, note="非红线步骤自动验收"
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
    """仅当前 attempt 的租约持有者可完成步骤，并聚合工作流状态。"""
    now = outbox_service.utcnow()
    if step.red_line and succeeded:
        target = STEP_WAITING_HUMAN
    else:
        target = STEP_SUCCEEDED if succeeded else STEP_FAILED
    result = await db.execute(
        update(WorkflowStep)
        .where(
            WorkflowStep.id == step.id,
            WorkflowStep.status == STEP_RUNNING,
            WorkflowStep.lease_owner == worker_id,
            WorkflowStep.attempt == step.attempt,
        )
        .values(
            status=target,
            output_data=output_data,
            lease_owner=None,
            lease_until=None,
            completed_at=now,
            last_error=error[:2000] if error else None,
            version=WorkflowStep.version + 1,
        )
        .execution_options(synchronize_session=False)
    )
    if getattr(result, "rowcount", 0) != 1:
        return False
    await db.flush()
    step.status = target
    step.output_data = output_data
    step.last_error = error
    await _mirror_step_result(db, step, result_content=result_content, succeeded=succeeded)
    run = await get_run(db, step.workflow_run_id)
    await append_event(
        db,
        run,
        "step.waiting_human" if target == STEP_WAITING_HUMAN else "step.completed",
        step=step,
        attempt=step.attempt,
        payload={"succeeded": succeeded, "error": error},
    )
    await refresh_run_status(db, run)
    return True


async def pipe_outputs(
    db: AsyncSession,
    step: WorkflowStep,
    *,
    datasets: list[dict[str, Any]],
    artifacts: list[dict[str, Any]],
) -> None:
    """把结构化产出引用写入直接下游步骤，不复制无关执行记录。"""
    if not datasets and not artifacts:
        return
    steps = await list_steps(db, step.workflow_run_id)
    sid = str(step.id)
    for downstream in steps:
        if sid not in (downstream.depends_on or []):
            continue
        data = dict(downstream.input_data or {})
        data["datasets"] = (data.get("datasets") or []) + datasets
        data["artifacts"] = (data.get("artifacts") or []) + artifacts
        downstream.input_data = data
    await db.flush()


async def refresh_run_status(db: AsyncSession, run: WorkflowRun) -> str:
    """按步骤状态持久化父流程终态，并同步父 TaskCard 镜像。"""
    steps = await list_steps(db, run.id)
    now = outbox_service.utcnow()
    if steps and all(step.status == STEP_SUCCEEDED for step in steps):
        status = RUN_SUCCEEDED
    elif any(step.status == STEP_CANCELLED for step in steps):
        status = RUN_CANCELLED
    elif any(step.status == STEP_FAILED for step in steps):
        status = RUN_FAILED
    elif any(step.status == STEP_WAITING_HUMAN for step in steps):
        status = RUN_WAITING_HUMAN
    elif any(step.status == STEP_RUNNING for step in steps):
        status = RUN_RUNNING
    elif any(step.status == STEP_SUCCEEDED for step in steps):
        status = RUN_RUNNING
    else:
        status = RUN_QUEUED
    changed = run.status != status
    run.status = status
    if status in (RUN_SUCCEEDED, RUN_FAILED, RUN_CANCELLED):
        run.completed_at = now
    if status == RUN_FAILED:
        run.error_msg = next(
            (step.last_error for step in steps if step.status == STEP_FAILED and step.last_error),
            "工作流步骤执行失败",
        )
    if changed:
        run.version += 1
        await append_event(db, run, f"workflow.{status}")
    if run.parent_task_id is not None:
        await _sync_parent_card(db, run)
    await db.flush()
    return status


async def _sync_parent_card(db: AsyncSession, run: WorkflowRun) -> None:
    card = await task_service.get_task(db, run.parent_task_id)  # type: ignore[arg-type]
    if (
        run.status
        in (
            RUN_RUNNING,
            RUN_WAITING_HUMAN,
            RUN_SUCCEEDED,
            RUN_FAILED,
            RUN_CANCELLED,
        )
        and card.status == task_flow.CREATED
    ):
        await task_service.transition(
            db, card.id, task_flow.DISPATCHED, operator_id=None, note="工作流启动"
        )
        await task_service.transition(
            db, card.id, task_flow.EXECUTING, operator_id=None, note="工作流执行中"
        )
    if run.status in (RUN_SUCCEEDED, RUN_FAILED) and card.status == task_flow.EXECUTING:
        await task_service.transition(
            db,
            card.id,
            task_flow.REPORTED,
            operator_id=None,
            note="工作流完成" if run.status == RUN_SUCCEEDED else "工作流失败",
            result_content="工作流已完成" if run.status == RUN_SUCCEEDED else run.error_msg,
        )
    if run.status == RUN_SUCCEEDED and card.status == task_flow.REPORTED:
        await task_service.transition(
            db, card.id, task_flow.ACCEPTED, operator_id=None, note="工作流聚合完成"
        )
    if run.status == RUN_CANCELLED and task_flow.can_transition(card.status, task_flow.CANCELLED):
        await task_service.transition(
            db, card.id, task_flow.CANCELLED, operator_id=None, note="工作流已取消"
        )


async def accept_human_step(
    db: AsyncSession,
    task_card_id: uuid.UUID,
    *,
    operator_id: uuid.UUID | None,
) -> WorkflowRun | None:
    """真人验收 TaskCard 镜像后，完成 waiting_human 步骤并事务性写 resume outbox。"""
    step = (
        await db.execute(
            select(WorkflowStep).where(
                WorkflowStep.task_card_id == task_card_id,
                WorkflowStep.status == STEP_WAITING_HUMAN,
            )
        )
    ).scalar_one_or_none()
    if step is None:
        return None
    step.status = STEP_SUCCEEDED
    step.version += 1
    step.completed_at = outbox_service.utcnow()
    run = await get_run(db, step.workflow_run_id)
    await append_event(
        db,
        run,
        "step.human_accepted",
        step=step,
        attempt=step.attempt,
        payload={"operator_id": str(operator_id) if operator_id else None},
    )
    await refresh_run_status(db, run)
    await outbox_service.enqueue(
        db,
        aggregate_type="workflow",
        aggregate_id=run.id,
        event_type="workflow.advance",
        dedupe_key=f"workflow:{run.id}:resume:{step.id}:{step.version}",
        payload={"workflow_run_id": str(run.id), "trace_id": str(run.trace_id)},
    )
    return run


async def fail_from_outbox(
    db: AsyncSession,
    event: Any,
    *,
    error: str,
) -> WorkflowRun | None:
    """outbox 重试耗尽时把失败显式传播到步骤/工作流和 TaskCard 镜像。"""
    raw_run_id = (event.payload or {}).get("workflow_run_id")
    if not raw_run_id:
        return None
    run = await get_run(db, uuid.UUID(str(raw_run_id)))
    raw_step_id = (event.payload or {}).get("workflow_step_id")
    if raw_step_id:
        step = await db.get(WorkflowStep, uuid.UUID(str(raw_step_id)))
        if step is not None and step.status not in (
            STEP_SUCCEEDED,
            STEP_WAITING_HUMAN,
            STEP_CANCELLED,
            STEP_FAILED,
        ):
            step.status = STEP_FAILED
            step.last_error = error[:2000]
            step.lease_owner = None
            step.lease_until = None
            step.completed_at = outbox_service.utcnow()
            step.version += 1
            await append_event(
                db,
                run,
                "step.retry_exhausted",
                step=step,
                attempt=step.attempt,
                payload={"outbox_event_id": str(event.id), "error": error[:2000]},
            )
            await refresh_run_status(db, run)
            return run
    run.status = RUN_FAILED
    run.error_msg = error[:2000]
    run.completed_at = outbox_service.utcnow()
    run.version += 1
    await append_event(
        db,
        run,
        "workflow.retry_exhausted",
        payload={"outbox_event_id": str(event.id), "error": error[:2000]},
    )
    if run.parent_task_id is not None:
        await _sync_parent_card(db, run)
    await db.flush()
    return run


async def progress(db: AsyncSession, parent_task_id: uuid.UUID) -> dict[str, Any]:
    """返回新工作流快照；旧 TaskCard 编排由调用方决定是否走兼容实现。"""
    run = await get_run_by_parent_task(db, parent_task_id)
    if run is None:
        raise AppError("工作流不存在", code=404, status_code=404)
    steps = await list_steps(db, run.id)
    completed = sum(1 for step in steps if step.status == STEP_SUCCEEDED)
    return {
        "workflow_id": str(run.id),
        "parent_id": str(parent_task_id),
        "parent_task_id": str(parent_task_id),
        "trace_id": str(run.trace_id),
        "status": run.status,
        "total": len(steps),
        "accepted": completed,
        "completed": completed,
        "done": run.status == RUN_SUCCEEDED,
        "awaiting_human": [
            str(step.task_card_id or step.id) for step in steps if step.status == STEP_WAITING_HUMAN
        ],
        "steps": [
            {
                "id": str(step.task_card_id or step.id),
                "task_card_id": str(step.task_card_id) if step.task_card_id else None,
                "workflow_step_id": str(step.id),
                "step_no": step.step_no,
                "title": step.title,
                "skill": step.skill,
                "status": step.status,
                "red_line": step.red_line,
                "attempt": step.attempt,
                "last_error": step.last_error,
                "output_data": step.output_data,
            }
            for step in steps
        ],
    }
