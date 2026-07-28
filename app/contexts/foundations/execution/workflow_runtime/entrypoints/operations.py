"""Published request-scoped Workflow Runtime operations."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.execution.workflow_runtime.application.ports import (
    TaskProjectionPort,
)
from app.contexts.foundations.execution.workflow_runtime.contracts.runtime import (
    StartWorkflowCommand,
    StartWorkflowResult,
)
from app.contexts.foundations.execution.workflow_runtime.infrastructure import (
    human_decisions,
    sqlalchemy_projection,
    sqlalchemy_repository,
)
from app.contexts.foundations.execution.workflow_runtime.infrastructure.sqlalchemy_uow import (
    SQLAlchemyWorkflowUnitOfWorkFactory,
)


async def start_workflow(
    session: AsyncSession,
    command: StartWorkflowCommand,
    *,
    task_projection: TaskProjectionPort,
) -> StartWorkflowResult:
    """Atomically persist a validated plan and its Task projections."""
    unit = SQLAlchemyWorkflowUnitOfWorkFactory(session, task_projection)()
    async with unit:
        try:
            result = await unit.workflows.start(command)
            await unit.commit()
            return result
        except Exception:
            await unit.rollback()
            raise


async def resume_task_step(
    session: AsyncSession,
    *,
    task_card_id: uuid.UUID,
    parent_task_id: uuid.UUID | None,
    step_number: int | None,
    operator_id: uuid.UUID,
    task_projection: TaskProjectionPort,
) -> dict[str, Any] | None:
    """Atomically record human acceptance and enqueue workflow continuation."""
    if step_number is None or parent_task_id is None:
        return None
    run = await human_decisions.accept_human_step(
        session,
        task_card_id,
        operator_id=operator_id,
        task_projection=task_projection,
    )
    if run is None:
        return None
    await session.commit()
    return await sqlalchemy_projection.progress(session, parent_task_id)


async def progress_for_task(
    session: AsyncSession,
    parent_task_id: uuid.UUID,
) -> dict[str, Any] | None:
    """Return durable workflow progress, or None when no durable run exists."""
    run = await sqlalchemy_repository.get_run_by_parent_task(session, parent_task_id)
    if run is None:
        return None
    return await sqlalchemy_projection.progress(session, parent_task_id)
