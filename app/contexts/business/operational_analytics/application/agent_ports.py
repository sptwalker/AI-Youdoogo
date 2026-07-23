"""Operational Analytics-owned ports for AI analysis and notification."""

from __future__ import annotations

from datetime import date
from typing import Protocol

from app.contexts.business.operational_analytics.agent_contracts import (
    MetricRowInput,
)
from app.contexts.foundations.execution.agent_execution.contracts.execution import (
    AgentExecutionRequest,
)
from app.contexts.foundations.execution.agent_execution.contracts.records import (
    AgentExecutionRecordView,
)
from app.contexts.foundations.workforce.expert_management.contracts.execution import (
    ExpertExecutionSnapshot,
)


class OperationalMetricHistoryPort(Protocol):
    async def list_for_date(self, stat_date: date) -> tuple[MetricRowInput, ...]: ...


class OperationalExpertPort(Protocol):
    async def get_by_code(self, code: str) -> ExpertExecutionSnapshot | None: ...


class OperationalAgentPort(Protocol):
    async def execute(self, request: AgentExecutionRequest) -> AgentExecutionRecordView: ...


class OperationalNotificationPort(Protocol):
    async def push(self, message: str) -> None: ...
