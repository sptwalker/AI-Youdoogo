"""收件箱优先级打分 + 去重（纯函数，docs/27 §五、A4）。

优先级 = 4 因子加权，权重可人工调（传 `InboxWeights` 覆盖默认）。因子取自当前待办投影
已有信号（priority / kind / create_time），真实的截止时间 / 影响面 / 上级显式关注度等强信号
在阶段 B 日程域、指标域落地后再替换启发式。不注入时钟——`now` 由调用方传入，故可离线单测。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

# 优先级字面量 → 紧急度分（缺省按 normal）
_URGENCY: dict[str, float] = {"high": 1.0, "urgent": 1.0, "normal": 0.5, "low": 0.2}
# 来源类型 → 重要度分（决议/提案是决策级，协作次之，普通任务最低）
_IMPORTANCE: dict[str, float] = {
    "resolution": 1.0,
    "proposal": 1.0,
    "collab": 0.7,
    "task": 0.5,
}
# 需上级关注的来源（进管理层桌面的审批/决议类）
_ATTENTION_KINDS = frozenset({"proposal", "resolution"})
# 时效饱和窗：越久未处理越靠前，48h 达上限
_STALE_SATURATION = timedelta(hours=48)


@dataclass(frozen=True, slots=True)
class InboxWeights:
    """4 因子权重（可人工调）。默认相加为 1，打分即落在 [0,1]。"""

    urgency: float = 0.4
    importance: float = 0.25
    attention: float = 0.2
    staleness: float = 0.15


DEFAULT_WEIGHTS = InboxWeights()


def priority_score(
    kind: str,
    priority: str,
    create_time: datetime,
    now: datetime,
    weights: InboxWeights = DEFAULT_WEIGHTS,
) -> float:
    """4 因子加权打分（越大越靠前），四因子各归一到 [0,1] 再按权重线性合成。"""
    urgency = _URGENCY.get(priority, 0.5)
    importance = _IMPORTANCE.get(kind, 0.5)
    attention = 1.0 if kind in _ATTENTION_KINDS else 0.0
    age = now - create_time
    staleness = min(max(age / _STALE_SATURATION, 0.0), 1.0)
    return round(
        weights.urgency * urgency
        + weights.importance * importance
        + weights.attention * attention
        + weights.staleness * staleness,
        6,
    )


def dedupe_keys(items: list[tuple[str, object]]) -> list[tuple[str, object]]:
    """按 (kind, id) 去重合并，保留首次出现顺序（同一来源不重复占位）。"""
    seen: set[tuple[str, object]] = set()
    out: list[tuple[str, object]] = []
    for key in items:
        if key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out
