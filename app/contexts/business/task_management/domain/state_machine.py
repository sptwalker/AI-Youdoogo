"""Task lifecycle invariants owned by Task Management."""

from __future__ import annotations

from app.contexts.shared_kernel import RuleViolation

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
TRANSITIONS: dict[str, frozenset[str]] = {
    CREATED: frozenset({DISPATCHED, CANCELLED}),
    DISPATCHED: frozenset({EXECUTING, CANCELLED}),
    EXECUTING: frozenset({REPORTED, CANCELLED}),
    REPORTED: frozenset({ACCEPTED, REJECTED}),
    REJECTED: frozenset({DISPATCHED, CANCELLED}),
    ACCEPTED: frozenset(),
    CANCELLED: frozenset(),
}
TERMINAL: frozenset[str] = frozenset({ACCEPTED, CANCELLED})
# 仅「未开跑」的任务可编辑/补指派：created 尚未分发、rejected 待重新分发。
EDITABLE: frozenset[str] = frozenset({CREATED, REJECTED})


def can_transition(from_status: str, to_status: str) -> bool:
    return to_status in TRANSITIONS.get(from_status, frozenset())


def assert_editable(status: str) -> None:
    if status not in EDITABLE:
        allowed = "、".join(sorted(EDITABLE))
        raise RuleViolation(f"任务当前状态 {status} 不可编辑；仅 {allowed} 可编辑/补指派")


def assert_transition(from_status: str, to_status: str) -> None:
    if to_status not in STATES:
        raise RuleViolation(f"未知任务状态：{to_status}")
    if not can_transition(from_status, to_status):
        allowed = "、".join(sorted(TRANSITIONS.get(from_status, frozenset()))) or "无（终态）"
        raise RuleViolation(
            f"非法状态流转：{from_status} → {to_status}；当前可流转至：{allowed}"
        )
