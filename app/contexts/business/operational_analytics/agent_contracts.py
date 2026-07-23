"""Plain Operational Analytics commands and AI-analysis results."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.contexts.foundations.execution.agent_execution.contracts.records import (
    AgentExecutionRecordView,
)


@dataclass(frozen=True, slots=True)
class MetricRowInput:
    stat_date: str | None = None
    product: str | None = None
    dau: int | None = None
    new_users: int | None = None
    retention_d1: float | None = None

    def prompt_values(self) -> tuple[object, ...]:
        return (
            self.stat_date if self.stat_date is not None else "-",
            self.product if self.product is not None else "-",
            self.dau if self.dau is not None else "-",
            self.new_users if self.new_users is not None else "-",
            self.retention_d1 if self.retention_d1 is not None else "-",
        )


@dataclass(frozen=True, slots=True)
class MetricAlert:
    product: str
    metric: str
    severity: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {
            "product": self.product,
            "metric": self.metric,
            "severity": self.severity,
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class DailyReportCommand:
    stat_date: str
    rows: tuple[MetricRowInput, ...] | None = None
    operator_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class AnomalyCheckCommand:
    stat_date: str
    operator_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class AnomalyAlertCommand:
    stat_date: str
    alerts: tuple[MetricAlert, ...]
    operator_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class OperationalProposalCommand:
    topic: str
    context: str = ""
    operator_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class AnomalyCheckResult:
    alerts: tuple[MetricAlert, ...]
    record: AgentExecutionRecordView | None = None
