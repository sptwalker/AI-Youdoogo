"""Workflow status aggregation, TaskCard mirrors, and progress projection."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.shared_kernel import ResourceNotFound
from app.models.workflow import (
    RUN_CANCELLED,
    RUN_FAILED,
    RUN_QUEUED,
    RUN_RUNNING,
    RUN_SUCCEEDED,
    RUN_WAITING_HUMAN,
    STEP_CANCELLED,
    STEP_FAILED,
    STEP_RUNNING,
    STEP_SUCCEEDED,
    STEP_WAITING_HUMAN,
    WorkflowRun,
    WorkflowStep,
)
from app.services import outbox_service, task_flow, task_service, workflow_repository


async def mirror_step_running(db: AsyncSession, step: WorkflowStep) -> None:
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


async def mirror_step_result(
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


async def sync_parent_card(db: AsyncSession, run: WorkflowRun) -> None:
    card = await task_service.get_task(db, run.parent_task_id)  # type: ignore[arg-type]
    active = (RUN_RUNNING, RUN_WAITING_HUMAN, RUN_SUCCEEDED, RUN_FAILED, RUN_CANCELLED)
    if run.status in active and card.status == task_flow.CREATED:
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


async def refresh_run_status(db: AsyncSession, run: WorkflowRun) -> str:
    """按步骤状态持久化父流程终态，并同步父 TaskCard 镜像。"""
    steps = await workflow_repository.list_steps(db, run.id)
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
        await workflow_repository.append_event(db, run, f"workflow.{status}")
    if run.parent_task_id is not None:
        await sync_parent_card(db, run)
    await db.flush()
    return status


async def progress(db: AsyncSession, parent_task_id: uuid.UUID) -> dict[str, Any]:
    """返回新工作流快照；旧 TaskCard 编排由调用方决定是否走兼容实现。"""
    run = await workflow_repository.get_run_by_parent_task(db, parent_task_id)
    if run is None:
        raise ResourceNotFound("工作流不存在")
    steps = await workflow_repository.list_steps(db, run.id)
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
            str(step.task_card_id or step.id)
            for step in steps
            if step.status == STEP_WAITING_HUMAN
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
