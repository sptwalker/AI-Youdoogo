"""Usage and Budget-owned persistence, clock, counter, and alert ports."""

from __future__ import annotations

from typing import Protocol

from app.contexts.foundations.governance.usage_budget.contracts.usage import (
    BudgetPolicy,
    UsageRecordCommand,
)


class UsageRepositoryPort(Protocol):
    async def add(self, command: UsageRecordCommand) -> None: ...


class UsageUnitOfWork(Protocol):
    records: UsageRepositoryPort

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


class BudgetPolicyPort(Protocol):
    def current(self) -> BudgetPolicy: ...


class BudgetCounterPort(Protocol):
    def current(self, period: str) -> int: ...

    def add(self, period: str, tokens: int) -> int: ...


class UsageClockPort(Protocol):
    def current_period(self) -> str: ...


class BudgetAlertPort(Protocol):
    async def notify_exceeded(self, current: int, budget: int) -> None: ...


class UsageFailureReporterPort(Protocol):
    def record_failure(self, role: str, model: str | None) -> None: ...
