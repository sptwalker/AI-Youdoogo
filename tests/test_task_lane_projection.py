"""A3：看板泳道派生投影纯函数单测（离线、注入 now，裁决 #2 不动状态机）。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.contexts.business.task_management.domain import board, state_machine


def test_lane_covers_every_state() -> None:
    """每个执行态都映射到唯一用户泳道，无遗漏（新增态会在此暴露）。"""
    expected = {
        state_machine.CREATED: board.PENDING,
        state_machine.DISPATCHED: board.IN_PROGRESS,
        state_machine.EXECUTING: board.IN_PROGRESS,
        state_machine.REPORTED: board.REVIEW,
        state_machine.ACCEPTED: board.DONE,
        state_machine.REJECTED: board.REJECTED,
        state_machine.CANCELLED: board.CANCELLED,
    }
    assert set(expected) == set(state_machine.STATES)
    for status, lane in expected.items():
        assert board.lane(status) == lane


def test_archived_overrides_active_lane() -> None:
    now = datetime.now(UTC)
    assert board.lane(state_machine.EXECUTING, archived_at=now) == board.ARCHIVED
    assert board.lane(state_machine.CREATED, archived_at=now) == board.ARCHIVED


def test_blocked_only_on_active_and_stale() -> None:
    now = datetime(2026, 8, 15, 12, tzinfo=UTC)
    fresh = now - timedelta(hours=1)
    stale = now - timedelta(hours=49)

    # 进行中 + >48h 无更新 → 阻塞
    assert board.is_blocked(state_machine.EXECUTING, stale, now) is True
    assert board.is_blocked(state_machine.DISPATCHED, stale, now) is True
    # 进行中但刚更新 → 不阻塞
    assert board.is_blocked(state_machine.EXECUTING, fresh, now) is False
    # 非进行中态一律不阻塞（即便很久没动）
    assert board.is_blocked(state_machine.CREATED, stale, now) is False
    assert board.is_blocked(state_machine.REPORTED, stale, now) is False
    assert board.is_blocked(state_machine.ACCEPTED, stale, now) is False


def test_blocked_waiting_flag_short_circuits() -> None:
    """巡检算出的「等待前置/他人」直接置阻塞，不看时间。"""
    now = datetime(2026, 8, 15, 12, tzinfo=UTC)
    just_now = now
    assert board.is_blocked(state_machine.EXECUTING, just_now, now, waiting=True) is True
    # 但非进行中态即使 waiting 也不阻塞（终态不该被标预警）
    assert board.is_blocked(state_machine.ACCEPTED, just_now, now, waiting=True) is False
