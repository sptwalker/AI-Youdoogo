"""Current usage-gate adapter behind a pure Agent port."""

from __future__ import annotations

from collections.abc import Callable

from app.contexts.foundations.execution.agent_execution.contracts.execution import (
    AgentExecutionRequest,
    ExecutionError,
)


class CurrentUsageAuthorizationAdapter:
    """Translate the current daily budget gate into a pure decision."""

    def __init__(self, budget_exceeded: Callable[[], bool]) -> None:
        self._budget_exceeded = budget_exceeded

    def authorize(self, request: AgentExecutionRequest) -> ExecutionError | None:
        del request
        if not self._budget_exceeded():
            return None
        return ExecutionError(
            code="budget_exceeded",
            message="已达当日 LLM 用量预算上限，暂停调用（请联系管理员调整预算）",
        )
