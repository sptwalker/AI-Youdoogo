"""Time Management 请求级入口：装配 Application 并执行单个用例（薄封装）。"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.business.time_management.application.contracts import (
    FocusSessionResult,
    ScheduleResult,
    TimeLogResult,
    WeeklyReviewResult,
)
from app.contexts.business.time_management.domain.models import PlannableItem
from app.contexts.business.time_management.infrastructure.composition import (
    build_time_management_application,
)


async def create_schedule(
    session: AsyncSession,
    *,
    owner_id: uuid.UUID,
    title: str,
    start_at: datetime,
    end_at: datetime,
    linked_task_id: uuid.UUID | None = None,
) -> ScheduleResult:
    return await build_time_management_application(session).create_schedule(
        owner_id=owner_id,
        title=title,
        start_at=start_at,
        end_at=end_at,
        linked_task_id=linked_task_id,
    )


async def suggest_schedules(
    session: AsyncSession,
    *,
    owner_id: uuid.UUID,
    items: list[PlannableItem],
    window_start: datetime,
    window_end: datetime,
) -> tuple[ScheduleResult, ...]:
    return await build_time_management_application(session).suggest_schedules(
        owner_id=owner_id,
        items=items,
        window_start=window_start,
        window_end=window_end,
    )


async def confirm_schedule(
    session: AsyncSession, schedule_id: uuid.UUID, *, owner_id: uuid.UUID
) -> ScheduleResult:
    return await build_time_management_application(session).confirm_schedule(
        schedule_id, owner_id=owner_id
    )


async def list_schedules(
    session: AsyncSession,
    *,
    owner_id: uuid.UUID,
    status: str | None = None,
    limit: int = 100,
) -> tuple[ScheduleResult, ...]:
    return await build_time_management_application(session).list_schedules(
        owner_id=owner_id, status=status, limit=limit
    )


async def start_focus(
    session: AsyncSession,
    *,
    owner_id: uuid.UUID,
    planned_minutes: int,
    intercept_notifications: bool = True,
) -> FocusSessionResult:
    return await build_time_management_application(session).start_focus(
        owner_id=owner_id,
        planned_minutes=planned_minutes,
        intercept_notifications=intercept_notifications,
    )


async def complete_focus(
    session: AsyncSession, focus_id: uuid.UUID, *, owner_id: uuid.UUID
) -> FocusSessionResult:
    return await build_time_management_application(session).complete_focus(
        focus_id, owner_id=owner_id
    )


async def abort_focus(
    session: AsyncSession, focus_id: uuid.UUID, *, owner_id: uuid.UUID
) -> FocusSessionResult:
    return await build_time_management_application(session).abort_focus(
        focus_id, owner_id=owner_id
    )


async def is_user_focus_intercepting(session: AsyncSession, user_id: uuid.UUID) -> bool:
    """收件人是否处于拦截通知的专注期——供点对点通知单点拦截判定。"""
    return await build_time_management_application(session).has_active_intercepting_focus(
        user_id
    )


async def log_time(
    session: AsyncSession,
    *,
    owner_id: uuid.UUID,
    category: str,
    minutes: int,
    logged_date: date,
    ref_task_id: uuid.UUID | None = None,
) -> TimeLogResult:
    return await build_time_management_application(session).log_time(
        owner_id=owner_id,
        category=category,
        minutes=minutes,
        logged_date=logged_date,
        ref_task_id=ref_task_id,
    )


async def weekly_review(
    session: AsyncSession, *, owner_id: uuid.UUID, in_week_of: date
) -> WeeklyReviewResult:
    return await build_time_management_application(session).weekly_review(
        owner_id=owner_id, in_week_of=in_week_of
    )
