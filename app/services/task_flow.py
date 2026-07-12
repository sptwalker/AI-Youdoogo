"""任务卡状态机（自研，替代 LangGraph；纯逻辑，无外部依赖）。

任务卡全流程：创建 → 分发 → 执行 → 汇报 → 验收/驳回，可随时终止。
「拆解」以创建带 parent_id 的子任务实现，不作为独立状态。
验收（accepted）是真人确认动作，落地 docs/04 红线：AI 仅建议/执行权，验收需真人。
"""

from __future__ import annotations

from app.core.exceptions import AppError

# 状态常量
CREATED = "created"
DISPATCHED = "dispatched"
EXECUTING = "executing"
REPORTED = "reported"
ACCEPTED = "accepted"
REJECTED = "rejected"
CANCELLED = "cancelled"

STATES: frozenset[str] = frozenset(
    {CREATED, DISPATCHED, EXECUTING, REPORTED, ACCEPTED, REJECTED, CANCELLED}
)

# 允许的状态迁移（from → 可达 to 集合）
TRANSITIONS: dict[str, frozenset[str]] = {
    CREATED: frozenset({DISPATCHED, CANCELLED}),
    DISPATCHED: frozenset({EXECUTING, CANCELLED}),
    EXECUTING: frozenset({REPORTED, CANCELLED}),
    REPORTED: frozenset({ACCEPTED, REJECTED}),
    REJECTED: frozenset({DISPATCHED, CANCELLED}),  # 驳回后可重新分发或终止
    ACCEPTED: frozenset(),
    CANCELLED: frozenset(),
}

# 终态：不可再迁出
TERMINAL: frozenset[str] = frozenset({ACCEPTED, CANCELLED})


def can_transition(from_status: str, to_status: str) -> bool:
    """判断状态迁移是否合法。"""
    return to_status in TRANSITIONS.get(from_status, frozenset())


def assert_transition(from_status: str, to_status: str) -> None:
    """校验状态迁移，非法则抛 AppError（供 service 层调用）。"""
    if to_status not in STATES:
        raise AppError(f"未知任务状态：{to_status}")
    if not can_transition(from_status, to_status):
        allowed = "、".join(sorted(TRANSITIONS.get(from_status, frozenset()))) or "无（终态）"
        raise AppError(f"非法状态流转：{from_status} → {to_status}；当前可流转至：{allowed}")
