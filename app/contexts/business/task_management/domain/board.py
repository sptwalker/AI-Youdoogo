"""看板泳道派生投影（纯函数，docs/27 §5.2 裁决 #2）。

对上把 durable 执行态映射为 PRD 用户面泳道；对下不动状态机。`blocked` 是叠加派生的
预警标记（非核心态）：进行中且长时间无更新，或显式等待前置/他人。全部为纯函数，
不注入时钟——`now` 由调用方传入，故可离线单测、可被巡检批量计算。
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.contexts.business.task_management.domain import state_machine

# 用户面泳道标签（docs/27 §5.2）
PENDING = "待启动"
IN_PROGRESS = "进行中"
REVIEW = "待审核"
DONE = "已完成"
REJECTED = "驳回"
CANCELLED = "已终止"
ARCHIVED = "已归档"

_LANE: dict[str, str] = {
    state_machine.CREATED: PENDING,
    state_machine.DISPATCHED: IN_PROGRESS,
    state_machine.EXECUTING: IN_PROGRESS,
    state_machine.REPORTED: REVIEW,
    state_machine.ACCEPTED: DONE,
    state_machine.REJECTED: REJECTED,
    state_machine.CANCELLED: CANCELLED,
}

# 「进行中」泳道对应的执行态（blocked 只在这些态上派生）
_ACTIVE: frozenset[str] = frozenset({state_machine.DISPATCHED, state_machine.EXECUTING})

STALE_AFTER = timedelta(hours=48)


def lane(status: str, archived_at: datetime | None = None) -> str:
    """执行态 → 用户泳道；已归档卡统一落「已归档」泳道（软标记优先于活动态）。"""
    if archived_at is not None:
        return ARCHIVED
    # 未知态兜底为「进行中」，避免看板漏卡（新增执行态时更保守）。
    return _LANE.get(status, IN_PROGRESS)


def is_blocked(
    status: str,
    updated_at: datetime,
    now: datetime,
    *,
    waiting: bool = False,
) -> bool:
    """派生阻塞预警：进行中且 >48h 无更新，或显式等待前置/他人。终态/待办不阻塞。"""
    if status not in _ACTIVE:
        return False
    if waiting:
        return True
    # ponytail: 仅按 update_time 判 48h 静止；缺前置输入/等待他人由巡检(阶段D)算出 waiting 传入
    return now - updated_at >= STALE_AFTER
