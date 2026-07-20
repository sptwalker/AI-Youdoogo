"""技能副作用幂等记录服务。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.contracts import ExecutionContext
from app.models.workflow import (
    TOOL_FAILED,
    TOOL_RUNNING,
    TOOL_SUCCEEDED,
    ToolExecution,
)


async def begin(
    db: AsyncSession,
    *,
    tool_key: str,
    idempotency_key: str,
    request_data: dict[str, Any],
    context: ExecutionContext,
) -> tuple[ToolExecution, bool]:
    """取得/创建执行记录；返回 (record, already_succeeded)。"""
    existing = (
        await db.execute(
            select(ToolExecution).where(ToolExecution.idempotency_key == idempotency_key)
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.status == TOOL_SUCCEEDED:
            return existing, True
        existing.status = TOOL_RUNNING
        existing.workflow_run_id = context.workflow_run_id
        existing.workflow_step_id = context.workflow_step_id
        existing.trace_id = context.trace_id
        existing.attempt = context.attempt or existing.attempt
        existing.request_data = request_data
        existing.error_msg = None
        await db.flush()
        return existing, False
    record = ToolExecution(
        workflow_run_id=context.workflow_run_id,
        workflow_step_id=context.workflow_step_id,
        trace_id=context.trace_id,
        attempt=context.attempt or 0,
        tool_key=tool_key,
        idempotency_key=idempotency_key,
        status=TOOL_RUNNING,
        request_data=request_data,
    )
    try:
        async with db.begin_nested():
            db.add(record)
            await db.flush()
    except IntegrityError:
        existing = (
            await db.execute(
                select(ToolExecution).where(ToolExecution.idempotency_key == idempotency_key)
            )
        ).scalar_one()
        return existing, existing.status == TOOL_SUCCEEDED
    return record, False


async def succeed(db: AsyncSession, record: ToolExecution, result_data: dict[str, Any]) -> None:
    record.status = TOOL_SUCCEEDED
    record.result_data = result_data
    record.error_msg = None
    await db.flush()


async def fail(db: AsyncSession, record: ToolExecution, error: str) -> None:
    record.status = TOOL_FAILED
    record.error_msg = error[:2000]
    await db.flush()
