"""Current database, settings, counter, notification, and clock adapters."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.governance.usage_budget.application.ports import (
    UsageRepositoryPort,
)
from app.contexts.foundations.governance.usage_budget.application.use_cases import (
    AuthorizeUsage,
    RecordUsage,
)
from app.contexts.foundations.governance.usage_budget.contracts.usage import (
    BudgetPolicy,
    UsageAuthorizationDecision,
    UsageRecordCommand,
)
from app.core import shared_state
from app.core.config import get_settings
from app.integrations.feishu import notify
from app.models.llm_log import LlmCallLog

logger = logging.getLogger(__name__)


class BudgetSettings(Protocol):
    llm_daily_token_budget: int
    llm_budget_hard_limit: bool


def _operations(session: AsyncSession) -> SQLAlchemyUsageBudget:
    return SQLAlchemyUsageBudget(session, settings_provider=get_settings, logger=logger)


def budget_exceeded() -> bool:
    return not authorize_current_usage(get_settings).allowed


def extract_usage(reply: object) -> tuple[int, int, int]:
    metadata: dict[str, Any] = getattr(reply, "usage_metadata", None) or {}
    prompt_tokens = int(metadata.get("input_tokens", 0) or 0)
    completion_tokens = int(metadata.get("output_tokens", 0) or 0)
    total_tokens = int(metadata.get("total_tokens", 0) or 0) or (
        prompt_tokens + completion_tokens
    )
    return prompt_tokens, completion_tokens, total_tokens


async def record_usage(
    session: AsyncSession,
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
    await _operations(session).record(
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


class SQLAlchemyUsageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, command: UsageRecordCommand) -> None:
        self._session.add(
            LlmCallLog(
                role=command.role,
                model=command.model,
                prompt_tokens=command.prompt_tokens,
                completion_tokens=command.completion_tokens,
                total_tokens=command.total_tokens,
                duration_ms=command.duration_ms,
                status=command.status,
                user_id=command.user_id,
                task_id=command.task_id,
                department_id=command.department_id,
                workflow_run_id=command.workflow_run_id,
                workflow_step_id=command.workflow_step_id,
                attempt_no=command.attempt_no,
                trace_id=command.trace_id,
            )
        )


class SQLAlchemyUsageUnitOfWork:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self.records: UsageRepositoryPort = SQLAlchemyUsageRepository(session)

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()


class SettingsBudgetPolicy:
    def __init__(self, settings_provider: Callable[[], BudgetSettings]) -> None:
        self._settings_provider = settings_provider

    def current(self) -> BudgetPolicy:
        settings = self._settings_provider()
        return BudgetPolicy(
            daily_token_budget=settings.llm_daily_token_budget,
            hard_limit=settings.llm_budget_hard_limit,
        )


class SharedStateBudgetCounter:
    def current(self, period: str) -> int:
        return shared_state.budget_add(period, 0)

    def add(self, period: str, tokens: int) -> int:
        return shared_state.budget_add(period, tokens)


class UTCUsageClock:
    def current_period(self) -> str:
        return datetime.now(UTC).strftime("%Y-%m-%d")


class FeishuBudgetAlert:
    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger

    async def notify_exceeded(self, current: int, budget: int) -> None:
        message = (
            f"LLM 日用量告警：当日累计 {current} tokens 已超预算 {budget}，请关注成本。"
        )
        self._logger.warning(message)
        await notify.push_ops_message(f"【成本告警】{message}")


class LoggingUsageFailureReporter:
    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger

    def record_failure(self, role: str, model: str | None) -> None:
        self._logger.exception("记录 LLM 用量失败 role=%s model=%s", role, model)


def authorize_current_usage(
    settings_provider: Callable[[], BudgetSettings],
) -> UsageAuthorizationDecision:
    return AuthorizeUsage(
        SettingsBudgetPolicy(settings_provider),
        SharedStateBudgetCounter(),
        UTCUsageClock(),
    ).execute()


class SQLAlchemyUsageBudget:
    def __init__(
        self,
        session: AsyncSession,
        *,
        settings_provider: Callable[[], BudgetSettings],
        logger: logging.Logger,
    ) -> None:
        policy = SettingsBudgetPolicy(settings_provider)
        counter = SharedStateBudgetCounter()
        clock = UTCUsageClock()
        self._authorize = AuthorizeUsage(policy, counter, clock)
        self._record = RecordUsage(
            SQLAlchemyUsageUnitOfWork(session),
            policy,
            counter,
            clock,
            FeishuBudgetAlert(logger),
            LoggingUsageFailureReporter(logger),
        )

    def authorize(self) -> UsageAuthorizationDecision:
        return self._authorize.execute()

    async def record(self, command: UsageRecordCommand) -> None:
        await self._record.execute(command)

    async def check_budget(self, tokens: int) -> None:
        await self._record.check_budget(tokens)
