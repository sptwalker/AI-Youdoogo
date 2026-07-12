"""运营指标异常检测（纯规则，无外部依赖）。

对比当日与前一日（或基线）指标，产出异常清单：日活/新增环比骤降、次留低于地板线。
阈值给默认值，业务方可 override（ponytail: 先固定规则，后续需要再做可配置策略）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class Alert:
    """一条指标异常。severity: warning / critical。"""

    product: str
    metric: str
    severity: str
    message: str


def _drop_ratio(prev: float, cur: float) -> float:
    """环比降幅（prev→cur），prev<=0 时返回 0（无基线不判降）。"""
    return (prev - cur) / prev if prev > 0 else 0.0


def detect_anomalies(
    today: list[dict[str, Any]],
    prev: list[dict[str, Any]],
    *,
    dau_drop_pct: float = 0.2,
    new_drop_pct: float = 0.3,
    retention_floor: float = 30.0,
) -> list[Alert]:
    """检测当日运营指标异常。

    Args:
        today/prev: 当日与前一日的指标行（get_ops_metrics 产物，按 product 对齐）。
        dau_drop_pct: 日活环比降幅告警阈值（0.2=降20%）。
        new_drop_pct: 新增环比降幅告警阈值。
        retention_floor: 次留地板线（百分比，低于即告警）。
    """
    prev_by_product = {r["product"]: r for r in prev}
    alerts: list[Alert] = []
    for row in today:
        product = row["product"]
        base = prev_by_product.get(product)

        dau = row.get("dau")
        if base and dau is not None and base.get("dau"):
            drop = _drop_ratio(base["dau"], dau)
            if drop >= dau_drop_pct:
                sev = "critical" if drop >= dau_drop_pct * 2 else "warning"
                alerts.append(
                    Alert(product, "dau", sev,
                          f"日活环比下降 {drop:.0%}（{base['dau']}→{dau}）")
                )

        new_users = row.get("new_users")
        if base and new_users is not None and base.get("new_users"):
            drop = _drop_ratio(base["new_users"], new_users)
            if drop >= new_drop_pct:
                alerts.append(
                    Alert(product, "new_users", "warning",
                          f"新增环比下降 {drop:.0%}（{base['new_users']}→{new_users}）")
                )

        retention = row.get("retention_d1")
        if retention is not None and retention < retention_floor:
            alerts.append(
                Alert(product, "retention_d1", "warning",
                      f"次留 {retention}% 低于地板线 {retention_floor}%")
            )
    return alerts
