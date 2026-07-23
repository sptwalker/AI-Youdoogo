"""Authorize usage and append usage evidence without touching source aggregates."""

from __future__ import annotations

from app.contexts.foundations.governance.usage_budget.application.ports import (
    BudgetAlertPort,
    BudgetCounterPort,
    BudgetPolicyPort,
    UsageClockPort,
    UsageFailureReporterPort,
    UsageUnitOfWork,
)
from app.contexts.foundations.governance.usage_budget.contracts.usage import (
    UsageAuthorizationDecision,
    UsageRecordCommand,
)
from app.contexts.foundations.governance.usage_budget.domain.policies import (
    authorize_usage,
    crossed_budget,
)


class AuthorizeUsage:
    def __init__(
        self,
        policy: BudgetPolicyPort,
        counter: BudgetCounterPort,
        clock: UsageClockPort,
    ) -> None:
        self._policy = policy
        self._counter = counter
        self._clock = clock

    def execute(self) -> UsageAuthorizationDecision:
        policy = self._policy.current()
        if policy.daily_token_budget <= 0 or not policy.hard_limit:
            return authorize_usage(policy, 0)
        current = self._counter.current(self._clock.current_period())
        return authorize_usage(policy, current)


class RecordUsage:
    def __init__(
        self,
        unit: UsageUnitOfWork,
        policy: BudgetPolicyPort,
        counter: BudgetCounterPort,
        clock: UsageClockPort,
        alerts: BudgetAlertPort,
        failures: UsageFailureReporterPort,
    ) -> None:
        self._unit = unit
        self._policy = policy
        self._counter = counter
        self._clock = clock
        self._alerts = alerts
        self._failures = failures

    async def execute(self, command: UsageRecordCommand) -> None:
        try:
            await self._unit.records.add(command)
            await self._unit.commit()
            await self.check_budget(command.total_tokens)
        except Exception:  # noqa: BLE001 - usage evidence never blocks source execution
            self._failures.record_failure(command.role, command.model)

    async def check_budget(self, tokens: int) -> None:
        policy = self._policy.current()
        if policy.daily_token_budget <= 0:
            return
        period = self._clock.current_period()
        before = self._counter.current(period)
        after = self._counter.add(period, max(0, tokens))
        if crossed_budget(before, after, policy.daily_token_budget):
            await self._alerts.notify_exceeded(after, policy.daily_token_budget)
