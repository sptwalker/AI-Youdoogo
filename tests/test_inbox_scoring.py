"""A4：收件箱优先级打分 + 去重纯函数单测（离线注入 now）。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.contexts.business.work_desktop.domain import inbox


def test_decision_grade_stale_high_beats_low_fresh_task() -> None:
    now = datetime(2026, 8, 15, 12, tzinfo=UTC)
    stale = now - timedelta(hours=60)
    hot = inbox.priority_score("resolution", "high", stale, now)
    cold = inbox.priority_score("task", "low", now, now)
    assert hot == 1.0  # 四因子全满 + 默认权重和为 1
    assert cold < hot
    assert 0.0 <= cold <= 1.0


def test_weights_are_adjustable_and_flip_ranking() -> None:
    now = datetime(2026, 8, 15, 12, tzinfo=UTC)
    stale_low = now - timedelta(hours=60)  # 低优先级但很久没动
    fresh_high = now  # 高优先级但刚到

    # 默认权重：紧急度权重最大 → 高优先级新任务靠前
    assert inbox.priority_score("task", "high", fresh_high, now) > inbox.priority_score(
        "task", "low", stale_low, now
    )
    # 只看时效的权重 → 陈旧项反超
    stale_only = inbox.InboxWeights(urgency=0.0, importance=0.0, attention=0.0, staleness=1.0)
    assert inbox.priority_score(
        "task", "low", stale_low, now, stale_only
    ) > inbox.priority_score("task", "high", fresh_high, now, stale_only)


def test_dedupe_keeps_first_occurrence_order() -> None:
    keys = [("task", 1), ("task", 1), ("proposal", 2), ("task", 3), ("proposal", 2)]
    assert inbox.dedupe_keys(keys) == [("task", 1), ("proposal", 2), ("task", 3)]
