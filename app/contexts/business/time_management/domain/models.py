"""Time Management 领域模型：日程 / 专注番茄钟 / 时间记录三聚合 + 固定规则排程算法。

纯领域对象，不依赖 ORM/框架。红线（docs/27-B §四）：
- Schedule 智能排程只出建议（source=suggested/status=suggested），真人 confirm 才生效（confirmed）。
- FocusSession 拦截只影响发给本人的点对点通知，不改对外红线。
linked_task_id/ref_task_id 为软引用（仅存 id，不建 FK）。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from app.contexts.shared_kernel import RuleViolation

# Schedule 状态：建议态 / 已确认（生效）/ 已完成 / 已取消。
SUGGESTED = "suggested"
CONFIRMED = "confirmed"
DONE = "done"
CANCELLED = "cancelled"
# Schedule 来源。
SOURCE_MANUAL = "manual"
SOURCE_SUGGESTED = "suggested"
# FocusSession 状态。
FOCUS_ACTIVE = "active"
FOCUS_COMPLETED = "completed"
FOCUS_ABORTED = "aborted"


@dataclass(slots=True)
class Schedule:
    """日程聚合根。手动建即 confirmed；智能建议为 suggested，confirm 后才生效。"""

    id: uuid.UUID
    owner_id: uuid.UUID
    title: str
    start_at: datetime
    end_at: datetime
    source: str
    status: str
    linked_task_id: uuid.UUID | None
    create_time: datetime | None = None

    @classmethod
    def create_manual(
        cls,
        *,
        schedule_id: uuid.UUID,
        owner_id: uuid.UUID,
        title: str,
        start_at: datetime,
        end_at: datetime,
        linked_task_id: uuid.UUID | None,
        created_at: datetime,
    ) -> Schedule:
        return cls(
            id=schedule_id,
            owner_id=owner_id,
            title=_clean_title(title),
            start_at=start_at,
            end_at=_valid_end(start_at, end_at),
            source=SOURCE_MANUAL,
            status=CONFIRMED,
            linked_task_id=linked_task_id,
            create_time=created_at,
        )

    @classmethod
    def create_suggested(
        cls,
        *,
        schedule_id: uuid.UUID,
        owner_id: uuid.UUID,
        title: str,
        start_at: datetime,
        end_at: datetime,
        linked_task_id: uuid.UUID | None,
        created_at: datetime,
    ) -> Schedule:
        """智能排程建议：建议态不占用、不通知，真人 confirm 才生效（docs/27-B §四红线）。"""
        return cls(
            id=schedule_id,
            owner_id=owner_id,
            title=_clean_title(title),
            start_at=start_at,
            end_at=_valid_end(start_at, end_at),
            source=SOURCE_SUGGESTED,
            status=SUGGESTED,
            linked_task_id=linked_task_id,
            create_time=created_at,
        )

    def confirm(self) -> None:
        if self.status != SUGGESTED:
            raise RuleViolation("仅建议态日程可确认")
        self.status = CONFIRMED


@dataclass(slots=True)
class FocusSession:
    """专注/番茄钟聚合根。active 期 intercept_notifications=True 则拦截发给本人的点对点通知。"""

    id: uuid.UUID
    owner_id: uuid.UUID
    start_at: datetime
    planned_minutes: int
    status: str
    intercept_notifications: bool
    ended_at: datetime | None
    create_time: datetime | None = None

    @classmethod
    def start(
        cls,
        *,
        focus_id: uuid.UUID,
        owner_id: uuid.UUID,
        planned_minutes: int,
        intercept_notifications: bool,
        started_at: datetime,
    ) -> FocusSession:
        if planned_minutes <= 0:
            raise RuleViolation("专注时长必须为正")
        return cls(
            id=focus_id,
            owner_id=owner_id,
            start_at=started_at,
            planned_minutes=planned_minutes,
            status=FOCUS_ACTIVE,
            intercept_notifications=intercept_notifications,
            ended_at=None,
            create_time=started_at,
        )

    def complete(self, *, at: datetime) -> None:
        self._end(FOCUS_COMPLETED, at)

    def abort(self, *, at: datetime) -> None:
        self._end(FOCUS_ABORTED, at)

    def _end(self, status: str, at: datetime) -> None:
        if self.status != FOCUS_ACTIVE:
            raise RuleViolation("专注会话已结束")
        self.status = status
        self.ended_at = at

    def is_intercepting(self) -> bool:
        return self.status == FOCUS_ACTIVE and self.intercept_notifications


@dataclass(slots=True)
class TimeLog:
    """时间记录聚合根：本人某日某分类耗时（分钟），供周复盘聚合。"""

    id: uuid.UUID
    owner_id: uuid.UUID
    category: str
    minutes: int
    logged_date: date
    ref_task_id: uuid.UUID | None
    create_time: datetime | None = None

    @classmethod
    def create(
        cls,
        *,
        log_id: uuid.UUID,
        owner_id: uuid.UUID,
        category: str,
        minutes: int,
        logged_date: date,
        ref_task_id: uuid.UUID | None,
        created_at: datetime,
    ) -> TimeLog:
        if minutes <= 0:
            raise RuleViolation("耗时必须为正")
        return cls(
            id=log_id,
            owner_id=owner_id,
            category=_clean_title(category),
            minutes=minutes,
            logged_date=logged_date,
            ref_task_id=ref_task_id,
            create_time=created_at,
        )


# --- 固定规则排程算法（纯函数，可单测；红线：仅产建议，不落库、不通知） -----------------


@dataclass(frozen=True, slots=True)
class PlannableItem:
    """待排任务：来自 task Context 的候选（id/标题/优先级/预估时长/截止）。"""

    ref_task_id: uuid.UUID
    title: str
    priority: int  # 越大越紧急
    duration_minutes: int
    due_at: datetime | None


@dataclass(frozen=True, slots=True)
class SuggestedSlot:
    ref_task_id: uuid.UUID
    title: str
    start_at: datetime
    end_at: datetime


def plan_suggestions(
    *,
    items: list[PlannableItem],
    busy: list[tuple[datetime, datetime]],
    window_start: datetime,
    window_end: datetime,
) -> list[SuggestedSlot]:
    """固定规则排程：按 (due 升序, 优先级降序) 贪心塞进窗口内最早的足够空档。

    ponytail: 固定规则排程，有行为数据后再上个性化学习（docs/27 §九）。
    """
    ordered = sorted(
        items,
        key=lambda it: (it.due_at is None, it.due_at or window_end, -it.priority),
    )
    gaps = _free_gaps(busy, window_start, window_end)
    suggestions: list[SuggestedSlot] = []
    for item in ordered:
        need = timedelta(minutes=item.duration_minutes)
        for i, (gap_start, gap_end) in enumerate(gaps):
            if gap_end - gap_start >= need:
                end = gap_start + need
                suggestions.append(
                    SuggestedSlot(
                        ref_task_id=item.ref_task_id,
                        title=item.title,
                        start_at=gap_start,
                        end_at=end,
                    )
                )
                gaps[i] = (end, gap_end)  # 缩小该空档，供后续任务续排
                break
    return suggestions


def _free_gaps(
    busy: list[tuple[datetime, datetime]],
    window_start: datetime,
    window_end: datetime,
) -> list[tuple[datetime, datetime]]:
    """求窗口内的空闲区间：把占用区间裁剪到窗口、排序、取补集。"""
    clipped = sorted(
        (max(s, window_start), min(e, window_end))
        for s, e in busy
        if min(e, window_end) > max(s, window_start)
    )
    gaps: list[tuple[datetime, datetime]] = []
    cursor = window_start
    for start, end in clipped:
        if start > cursor:
            gaps.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < window_end:
        gaps.append((cursor, window_end))
    return gaps


def _clean_title(text: str) -> str:
    cleaned = text.strip()
    if not cleaned:
        raise RuleViolation("内容不能为空")
    return cleaned


def _valid_end(start_at: datetime, end_at: datetime) -> datetime:
    if end_at <= start_at:
        raise RuleViolation("结束时间必须晚于开始时间")
    return end_at
