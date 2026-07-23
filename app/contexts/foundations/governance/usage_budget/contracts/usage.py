"""Pure usage evidence and budget decisions."""

from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class UsageRecordCommand:
    role: str
    model: str | None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    duration_ms: int | None = None
    status: str = "success"
    user_id: uuid.UUID | None = None
    task_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    workflow_run_id: uuid.UUID | None = None
    workflow_step_id: uuid.UUID | None = None
    attempt_no: int | None = None
    trace_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class BudgetPolicy:
    daily_token_budget: int
    hard_limit: bool


@dataclass(frozen=True, slots=True)
class UsageAuthorizationDecision:
    allowed: bool
    current_tokens: int
    daily_token_budget: int
    code: str = "allowed"
    reason: str = ""
