"""Durable orchestration facade with an explicit legacy TaskCard adapter."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.workflow_engine import get_workflow_engine
from app.llm import get_llm_for_role
from app.models.task import TaskCard
from app.services import legacy_orchestration, workflow_service
from app.services.workflow_planning import (
    MAX_STEPS as _MAX_STEPS,
)
from app.services.workflow_planning import (
    PlanStep,
    build_steps,
    is_red_line,
    parse_plan,
)

__all__ = [
    "PlanStep",
    "_MAX_STEPS",
    "advance",
    "build_steps",
    "is_red_line",
    "parse_plan",
    "plan",
    "progress",
    "recover_incomplete",
    "resume_if_step",
    "start",
]

logger = logging.getLogger(__name__)
_MIN_REQUEST_LEN = 8

# Compatibility exports for legacy tests/callers during migration.
_step_cards = legacy_orchestration.step_cards
_ready_steps = legacy_orchestration.ready_steps
_render_dataset = legacy_orchestration.render_dataset
_step_message = legacy_orchestration.step_message
_run_step = legacy_orchestration.run_step
_to_reported = legacy_orchestration.to_reported
_pipe_outputs = legacy_orchestration.pipe_outputs
_kickoff_parent = legacy_orchestration.kickoff_parent


async def plan(db: AsyncSession, request: str) -> list[PlanStep] | None:
    """兼容入口：注入 facade 上可替换的 LLM factory。"""
    from app.services import workflow_planning

    return await workflow_planning.plan(db, request, llm_factory=get_llm_for_role)


async def advance(
    db: AsyncSession, parent_id: uuid.UUID, *, operator_id: uuid.UUID | None
) -> dict[str, Any]:
    """显式委派旧 TaskCard-only 同步执行器。"""
    return await legacy_orchestration.advance(
        db,
        parent_id,
        operator_id=operator_id,
        step_runner=_run_step,
    )


async def start(
    db: AsyncSession,
    request: str,
    *,
    creator_id: uuid.UUID,
    assignee_agent_id: uuid.UUID | None,
    operator_id: uuid.UUID | None,
    title: str | None = None,
) -> dict[str, Any] | None:
    """规划后原子提交持久化工作流；HTTP 路径不执行 DAG。"""
    del operator_id
    if not request or len(request.strip()) < _MIN_REQUEST_LEN:
        return None
    try:
        steps = await plan(db, request)
        if steps is None:
            return None
        engine = get_workflow_engine()
        run = await engine.submit(
            db,
            request=request.strip(),
            title=(title or request.strip())[:200],
            creator_id=creator_id,
            assignee_agent_id=assignee_agent_id,
            steps=steps,
            is_red_line=is_red_line,
        )
        await db.commit()
        if run.parent_task_id is None:
            raise RuntimeError("工作流缺少父 TaskCard 镜像")
        return await engine.progress(db, run.parent_task_id)
    except Exception:  # noqa: BLE001
        await db.rollback()
        logger.warning("任务编排启动失败，退回普通处理", exc_info=True)
        return None


async def resume_if_step(
    db: AsyncSession, task: TaskCard, *, operator_id: uuid.UUID | None
) -> dict[str, Any] | None:
    if task.step_no is None or task.parent_id is None:
        return None
    engine = get_workflow_engine()
    run = await engine.accept_human_step(db, task, operator_id=operator_id)
    if run is not None:
        await db.commit()
        return await engine.progress(db, task.parent_id)
    return await advance(db, task.parent_id, operator_id=operator_id)


async def progress(db: AsyncSession, parent_id: uuid.UUID) -> dict[str, Any]:
    if await workflow_service.get_run_by_parent_task(db, parent_id) is not None:
        return await get_workflow_engine().progress(db, parent_id)
    return await legacy_orchestration.progress(db, parent_id)


async def recover_incomplete(db: AsyncSession) -> dict[str, int]:
    """迁移期旧 TaskCard-only 编排恢复入口。"""
    return await legacy_orchestration.recover_incomplete(db, advance_runner=advance)
