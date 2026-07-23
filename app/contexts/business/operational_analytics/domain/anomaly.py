"""Pure operational-metric anomaly rules."""

from __future__ import annotations

from app.contexts.business.operational_analytics.agent_contracts import (
    MetricAlert,
    MetricRowInput,
)


def _drop_ratio(previous: float, current: float) -> float:
    return (previous - current) / previous if previous > 0 else 0.0


def detect_metric_anomalies(
    today: tuple[MetricRowInput, ...],
    previous: tuple[MetricRowInput, ...],
    *,
    dau_drop_pct: float = 0.2,
    new_drop_pct: float = 0.3,
    retention_floor: float = 30.0,
) -> tuple[MetricAlert, ...]:
    previous_by_product = {
        row.product: row for row in previous if row.product is not None
    }
    alerts: list[MetricAlert] = []
    for row in today:
        product = row.product or ""
        baseline = previous_by_product.get(product)
        if baseline is not None and row.dau is not None and baseline.dau:
            drop = _drop_ratio(baseline.dau, row.dau)
            if drop >= dau_drop_pct:
                severity = "critical" if drop >= dau_drop_pct * 2 else "warning"
                alerts.append(
                    MetricAlert(
                        product,
                        "dau",
                        severity,
                        f"日活环比下降 {drop:.0%}（{baseline.dau}→{row.dau}）",
                    )
                )
        if baseline is not None and row.new_users is not None and baseline.new_users:
            drop = _drop_ratio(baseline.new_users, row.new_users)
            if drop >= new_drop_pct:
                alerts.append(
                    MetricAlert(
                        product,
                        "new_users",
                        "warning",
                        f"新增环比下降 {drop:.0%}（{baseline.new_users}→{row.new_users}）",
                    )
                )
        if row.retention_d1 is not None and row.retention_d1 < retention_floor:
            alerts.append(
                MetricAlert(
                    product,
                    "retention_d1",
                    "warning",
                    f"次留 {row.retention_d1}% 低于地板线 {retention_floor}%",
                )
            )
    return tuple(alerts)
