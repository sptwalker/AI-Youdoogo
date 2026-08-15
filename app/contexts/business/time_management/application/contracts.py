"""Time Management 应用层结果 DTO（与传输无关的纯数据）。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True, slots=True)
class ScheduleResult:
    id: uuid.UUID
    owner_id: uuid.UUID
    title: str
    start_at: datetime
    end_at: datetime
    source: str
    status: str
    linked_task_id: uuid.UUID | None
    create_time: datetime


@dataclass(frozen=True, slots=True)
class FocusSessionResult:
    id: uuid.UUID
    owner_id: uuid.UUID
    start_at: datetime
    planned_minutes: int
    status: str
    intercept_notifications: bool
    ended_at: datetime | None
    create_time: datetime


@dataclass(frozen=True, slots=True)
class TimeLogResult:
    id: uuid.UUID
    owner_id: uuid.UUID
    category: str
    minutes: int
    logged_date: date
    ref_task_id: uuid.UUID | None
    create_time: datetime


@dataclass(frozen=True, slots=True)
class CategorySummary:
    category: str
    total_minutes: int


@dataclass(frozen=True, slots=True)
class WeeklyReviewResult:
    """周度时间复盘：本人本周分类耗时求和（顾问型产出，写本人视图，不外发）。"""

    owner_id: uuid.UUID
    week_start: date
    week_end: date
    total_minutes: int
    by_category: tuple[CategorySummary, ...]
