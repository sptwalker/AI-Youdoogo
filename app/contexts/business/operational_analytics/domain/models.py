"""Framework-independent daily metric write model."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.contexts.shared_kernel import RuleViolation


@dataclass(frozen=True, slots=True)
class DailyMetricUpsert:
    stat_date: date
    product: str
    source: str
    fields: dict[str, object]

    def validate(self) -> None:
        if not self.product.strip():
            raise RuleViolation("产品名称必填")
        if self.source not in {"excel", "thinkingdata"}:
            raise RuleViolation("运营指标来源无效")
