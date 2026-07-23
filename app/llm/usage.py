"""One-way compatibility facade for Usage and Budget governance."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from langchain_core.messages import BaseMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.governance.usage_budget.contracts.usage import (
    UsageRecordCommand,
)
from app.contexts.foundations.governance.usage_budget.infrastructure.current_adapters import (
    SQLAlchemyUsageBudget,
    authorize_current_usage,
)
from app.core.config import get_settings

logger = logging.getLogger(__name__)


class BudgetExceededError(RuntimeError):
    """当日 LLM token 预算已耗尽且开启硬闸。"""


def _operations(db: AsyncSession) -> SQLAlchemyUsageBudget:
    return SQLAlchemyUsageBudget(db, settings_provider=get_settings, logger=logger)


def budget_exceeded() -> bool:
    return not authorize_current_usage(get_settings).allowed


def extract_usage(reply: BaseMessage | object) -> tuple[int, int, int]:
    meta: dict[str, Any] = getattr(reply, "usage_metadata", None) or {}
    prompt = int(meta.get("input_tokens", 0) or 0)
    completion = int(meta.get("output_tokens", 0) or 0)
    total = int(meta.get("total_tokens", 0) or 0) or (prompt + completion)
    return prompt, completion, total


async def record_usage(
    db: AsyncSession,
    *,
    role: str,
    model: str | None,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
    duration_ms: int | None = None,
    status: str = "success",
    user_id: uuid.UUID | None = None,
    task_id: uuid.UUID | None = None,
    department_id: uuid.UUID | None = None,
    workflow_run_id: uuid.UUID | None = None,
    workflow_step_id: uuid.UUID | None = None,
    attempt_no: int | None = None,
    trace_id: uuid.UUID | None = None,
) -> None:
    await _operations(db).record(
        UsageRecordCommand(
            role=role,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            duration_ms=duration_ms,
            status=status,
            user_id=user_id,
            task_id=task_id,
            department_id=department_id,
            workflow_run_id=workflow_run_id,
            workflow_step_id=workflow_step_id,
            attempt_no=attempt_no,
            trace_id=trace_id,
        )
    )


async def _check_daily_budget(db: AsyncSession, tokens: int) -> None:
    await _operations(db).check_budget(tokens)
