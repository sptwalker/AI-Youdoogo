"""Task Management-owned synchronous TaskCard-only workflow fallback."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.contracts import SkillResult
from app.contexts.business.task_management.domain import state_machine as task_flow
from app.contexts.business.task_management.infrastructure.sqlalchemy_adapter import (
    SQLAlchemyTaskManagementAdapter,
)
from app.contexts.foundations.execution.agent_execution.public import (
    AgentExecutionRequest,
    AgentExecutionStatus,
    execute_agent,
)
from app.contexts.foundations.workforce.expert_management.public import (
    build_local_expert_directory_port,
)
from app.models.task import TaskCard

logger = logging.getLogger(__name__)
ProtocolResult = SkillResult
StepRunner = Callable[[AsyncSession, TaskCard, uuid.UUID | None], Awaitable[ProtocolResult | None]]
AdvanceRunner = Callable[..., Awaitable[dict[str, Any]]]
PREVIEW_ROWS = 30
MAX_STEPS = 8


def _tasks(db: AsyncSession) -> SQLAlchemyTaskManagementAdapter:
    return SQLAlchemyTaskManagementAdapter(db)


async def step_cards(db: AsyncSession, parent_id: uuid.UUID) -> list[TaskCard]:
    steps = await _tasks(db).list_records(parent_id=parent_id, limit=MAX_STEPS + 2)
    return sorted(steps, key=lambda step: step.step_no if step.step_no is not None else 0)


def ready_steps(steps: list[TaskCard]) -> list[TaskCard]:
    done = {str(step.id) for step in steps if step.status == task_flow.ACCEPTED}
    return [
        step
        for step in steps
        if step.status in (task_flow.CREATED, task_flow.DISPATCHED)
        and all(dep in done for dep in (step.depends_on or []))
    ]


def render_dataset(dataset: dict[str, Any]) -> str:
    columns = dataset.get("columns") or []
    rows = dataset.get("rows") or []
    if not rows:
        return f"（查询 {dataset.get('sql', '')[:40]} 无数据）"
    head = "| " + " | ".join(str(column) for column in columns) + " |"
    sep = "| " + " | ".join("---" for _ in columns) + " |"
    body = [
        "| " + " | ".join(str(row.get(column, "")) for column in columns) + " |"
        for row in rows[:PREVIEW_ROWS]
    ]
    return "\n".join([head, sep, *body])


def step_message(step: TaskCard) -> str:
    payload = step.payload or {}
    parts = [f"任务：{step.title}", f"要求：{payload.get('instruction', step.title)}"]
    step_input = step.step_input or {}
    datasets = step_input.get("datasets") or []
    if datasets:
        parts.append("\n上游步骤已取得以下真实数据，请据此完成本步（勿另行编造）：")
        parts.extend(render_dataset(dataset) for dataset in datasets)
    artifacts = step_input.get("artifacts") or []
    if artifacts:
        parts.append(f"\n上游已产出文件：{'、'.join(a.get('file_name', '') for a in artifacts)}")
    parts.append("\n请完成本步骤。需要数据用【取数】指令，需生成文件用【交付】指令。")
    return "\n".join(parts)


async def to_reported(
    db: AsyncSession,
    step: TaskCard,
    operator_id: uuid.UUID | None,
    note: str,
    result: str | None,
) -> None:
    if step.status == task_flow.EXECUTING:
        await _tasks(db).transition_record(
            step.id,
            task_flow.REPORTED,
            operator_id=operator_id,
            note=note,
            result_content=result,
        )
        return
    for target in (task_flow.DISPATCHED, task_flow.EXECUTING, task_flow.REPORTED):
        if task_flow.can_transition(step.status, target):
            await _tasks(db).transition_record(
                step.id,
                target,
                operator_id=operator_id,
                note=note,
                result_content=result if target == task_flow.REPORTED else None,
            )


async def run_step(
    db: AsyncSession, step: TaskCard, operator_id: uuid.UUID | None
) -> ProtocolResult | None:
    expert = (
        await build_local_expert_directory_port(db).get_execution(step.assignee_agent_id)
        if step.assignee_agent_id
        else None
    )
    if expert is None:
        await to_reported(db, step, operator_id, "步骤无可用执行者", None)
        return None
    if step.status == task_flow.CREATED:
        await _tasks(db).transition_record(
            step.id, task_flow.DISPATCHED, operator_id=operator_id, note="编排分发"
        )
    await _tasks(db).transition_record(
        step.id, task_flow.EXECUTING, operator_id=operator_id, note="编排执行"
    )
    execution = await execute_agent(
        db,
        AgentExecutionRequest(
            expert=expert,
            task_type=step.task_type,
            input_summary=f"编排步骤：{step.title[:40]}",
            user_message=step_message(step),
            user_id=operator_id,
            use_knowledge=True,
        ),
    )
    text = (
        execution.content or (execution.error.message if execution.error else None) or "（无产出）"
    )
    await to_reported(
        db,
        step,
        expert.expert_id,
        f"执行 status={execution.status.value}",
        text,
    )
    return None if execution.status is AgentExecutionStatus.FAILED else SkillResult()


async def pipe_outputs(
    db: AsyncSession, step: TaskCard, result: ProtocolResult, all_steps: list[TaskCard]
) -> None:
    if not (result.datasets or result.artifacts):
        return
    step_id = str(step.id)
    for downstream in all_steps:
        if step_id not in (downstream.depends_on or []):
            continue
        step_input = dict(downstream.step_input or {})
        step_input["datasets"] = (step_input.get("datasets") or []) + result.datasets
        step_input["artifacts"] = (step_input.get("artifacts") or []) + result.artifacts
        downstream.step_input = step_input
    await db.commit()


async def kickoff_parent(
    db: AsyncSession, parent_id: uuid.UUID, operator_id: uuid.UUID | None
) -> None:
    parent = await _tasks(db).get_record(parent_id)
    if parent.status == task_flow.CREATED:
        await _tasks(db).transition_record(
            parent_id, task_flow.DISPATCHED, operator_id=operator_id, note="编排启动"
        )
        await _tasks(db).transition_record(
            parent_id, task_flow.EXECUTING, operator_id=operator_id, note="编排执行中"
        )


async def progress(db: AsyncSession, parent_id: uuid.UUID) -> dict[str, Any]:
    steps = await step_cards(db, parent_id)
    accepted = sum(1 for step in steps if step.status == task_flow.ACCEPTED)
    waiting = [step for step in steps if step.status == task_flow.REPORTED]
    return {
        "parent_id": str(parent_id),
        "total": len(steps),
        "accepted": accepted,
        "awaiting_human": [
            str(step.id) for step in waiting if (step.payload or {}).get("red_line")
        ],
        "done": accepted == len(steps) and bool(steps),
        "steps": [
            {
                "id": str(step.id),
                "step_no": step.step_no,
                "title": step.title,
                "skill": step.task_type,
                "status": step.status,
                "red_line": bool((step.payload or {}).get("red_line")),
            }
            for step in steps
        ],
    }


async def advance(
    db: AsyncSession,
    parent_id: uuid.UUID,
    *,
    operator_id: uuid.UUID | None,
    step_runner: StepRunner = run_step,
) -> dict[str, Any]:
    await kickoff_parent(db, parent_id, operator_id)
    while True:
        steps = await step_cards(db, parent_id)
        ready = ready_steps(steps)
        if not ready:
            break
        progressed = False
        for step in ready:
            result = await step_runner(db, step, operator_id)
            if result is None or (step.payload or {}).get("red_line"):
                continue
            await _tasks(db).transition_record(
                step.id,
                task_flow.ACCEPTED,
                operator_id=operator_id,
                note="非红线步骤自动验收",
            )
            await pipe_outputs(db, step, result, steps)
            progressed = True
        if not progressed:
            break
    return await progress(db, parent_id)


async def recover_incomplete(
    db: AsyncSession,
    *,
    advance_runner: AdvanceRunner,
) -> dict[str, int]:
    result = {"orchestrations": 0, "steps_reset": 0}
    try:
        parents = list(
            (
                await db.execute(
                    select(TaskCard).where(
                        TaskCard.task_type == "orchestration",
                        TaskCard.status == task_flow.EXECUTING,
                        TaskCard.is_delete.is_(False),
                    )
                )
            ).scalars()
        )
    except Exception:  # noqa: BLE001
        logger.warning("崩溃恢复扫描查询失败", exc_info=True)
        return result
    for parent in parents:
        try:
            steps = await step_cards(db, parent.id)
            reset = 0
            for step in steps:
                if step.status in (task_flow.EXECUTING, task_flow.DISPATCHED):
                    step.status = task_flow.CREATED
                    reset += 1
            if reset:
                await db.commit()
                result["steps_reset"] += reset
            await advance_runner(db, parent.id, operator_id=None)
            result["orchestrations"] += 1
        except Exception:  # noqa: BLE001
            logger.warning("编排 %s 崩溃恢复失败", parent.id, exc_info=True)
    return result
