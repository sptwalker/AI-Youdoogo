"""Time Management 用例与事务归属。

行级隔离铁律（docs/27-B §四）：所有读写按 owner_id 归属；命中他人一律当不存在（ResourceNotFound）。
红线：智能排程只出建议（suggested），真人 confirm 才生效；番茄钟拦截仅影响发给本人的通知。
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta

from app.contexts.business.time_management.application.contracts import (
    CategorySummary,
    FocusSessionResult,
    ScheduleResult,
    TimeLogResult,
    WeeklyReviewResult,
)
from app.contexts.business.time_management.application.ports import (
    Clock,
    IdentifierPort,
    TimeManagementUnitOfWork,
    TimeManagementUnitOfWorkFactory,
)
from app.contexts.business.time_management.domain.models import (
    CONFIRMED,
    FocusSession,
    PlannableItem,
    Schedule,
    TimeLog,
    plan_suggestions,
)
from app.contexts.shared_kernel import ResourceNotFound


def _schedule_result(schedule: Schedule) -> ScheduleResult:
    assert schedule.create_time is not None
    return ScheduleResult(
        id=schedule.id,
        owner_id=schedule.owner_id,
        title=schedule.title,
        start_at=schedule.start_at,
        end_at=schedule.end_at,
        source=schedule.source,
        status=schedule.status,
        linked_task_id=schedule.linked_task_id,
        create_time=schedule.create_time,
    )


def _focus_result(focus: FocusSession) -> FocusSessionResult:
    assert focus.create_time is not None
    return FocusSessionResult(
        id=focus.id,
        owner_id=focus.owner_id,
        start_at=focus.start_at,
        planned_minutes=focus.planned_minutes,
        status=focus.status,
        intercept_notifications=focus.intercept_notifications,
        ended_at=focus.ended_at,
        create_time=focus.create_time,
    )


def _log_result(log: TimeLog) -> TimeLogResult:
    assert log.create_time is not None
    return TimeLogResult(
        id=log.id,
        owner_id=log.owner_id,
        category=log.category,
        minutes=log.minutes,
        logged_date=log.logged_date,
        ref_task_id=log.ref_task_id,
        create_time=log.create_time,
    )


class TimeManagementApplication:
    def __init__(
        self,
        *,
        uow_factory: TimeManagementUnitOfWorkFactory,
        clock: Clock,
        identifiers: IdentifierPort,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._identifiers = identifiers

    # --- 日程 ---------------------------------------------------------------

    async def create_schedule(
        self,
        *,
        owner_id: uuid.UUID,
        title: str,
        start_at: datetime,
        end_at: datetime,
        linked_task_id: uuid.UUID | None = None,
    ) -> ScheduleResult:
        schedule = Schedule.create_manual(
            schedule_id=self._identifiers.new_id(),
            owner_id=owner_id,
            title=title,
            start_at=start_at,
            end_at=end_at,
            linked_task_id=linked_task_id,
            created_at=self._clock.now(),
        )
        async with self._uow_factory() as uow:
            await uow.schedules.add(schedule)
            await uow.commit()
        return _schedule_result(schedule)

    async def suggest_schedules(
        self,
        *,
        owner_id: uuid.UUID,
        items: list[PlannableItem],
        window_start: datetime,
        window_end: datetime,
    ) -> tuple[ScheduleResult, ...]:
        """按已确认日程为占用、固定规则填空档，落库为建议态（不占用/不通知，待真人 confirm）。"""
        now = self._clock.now()
        async with self._uow_factory() as uow:
            confirmed = await uow.schedules.list_for_owner(
                owner_id=owner_id, status=CONFIRMED, limit=500
            )
            busy = [(s.start_at, s.end_at) for s in confirmed]
            slots = plan_suggestions(
                items=items,
                busy=busy,
                window_start=window_start,
                window_end=window_end,
            )
            created: list[Schedule] = []
            for slot in slots:
                schedule = Schedule.create_suggested(
                    schedule_id=self._identifiers.new_id(),
                    owner_id=owner_id,
                    title=slot.title,
                    start_at=slot.start_at,
                    end_at=slot.end_at,
                    linked_task_id=slot.ref_task_id,
                    created_at=now,
                )
                await uow.schedules.add(schedule)
                created.append(schedule)
            await uow.commit()
        return tuple(_schedule_result(s) for s in created)

    async def confirm_schedule(
        self, schedule_id: uuid.UUID, *, owner_id: uuid.UUID
    ) -> ScheduleResult:
        async with self._uow_factory() as uow:
            schedule = await self._load_schedule(uow, schedule_id, owner_id)
            schedule.confirm()
            await uow.schedules.save(schedule)
            await uow.commit()
        return _schedule_result(schedule)

    async def list_schedules(
        self, *, owner_id: uuid.UUID, status: str | None = None, limit: int = 100
    ) -> tuple[ScheduleResult, ...]:
        async with self._uow_factory() as uow:
            schedules = await uow.schedules.list_for_owner(
                owner_id=owner_id, status=status, limit=limit
            )
        return tuple(_schedule_result(s) for s in schedules)

    # --- 专注番茄钟 ---------------------------------------------------------

    async def start_focus(
        self,
        *,
        owner_id: uuid.UUID,
        planned_minutes: int,
        intercept_notifications: bool = True,
    ) -> FocusSessionResult:
        async with self._uow_factory() as uow:
            if await uow.focus_sessions.active_for_owner(owner_id) is not None:
                raise ResourceNotFound("已有进行中的专注会话")  # 幂等保护，避免并发双开
            focus = FocusSession.start(
                focus_id=self._identifiers.new_id(),
                owner_id=owner_id,
                planned_minutes=planned_minutes,
                intercept_notifications=intercept_notifications,
                started_at=self._clock.now(),
            )
            await uow.focus_sessions.add(focus)
            await uow.commit()
        return _focus_result(focus)

    async def complete_focus(
        self, focus_id: uuid.UUID, *, owner_id: uuid.UUID
    ) -> FocusSessionResult:
        return await self._end_focus(focus_id, owner_id, abort=False)

    async def abort_focus(
        self, focus_id: uuid.UUID, *, owner_id: uuid.UUID
    ) -> FocusSessionResult:
        return await self._end_focus(focus_id, owner_id, abort=True)

    async def has_active_intercepting_focus(self, owner_id: uuid.UUID) -> bool:
        """收件人是否处于 active 且拦截通知的专注期——供点对点通知单点拦截判定。"""
        async with self._uow_factory() as uow:
            focus = await uow.focus_sessions.active_for_owner(owner_id)
        return focus is not None and focus.is_intercepting()

    async def _end_focus(
        self, focus_id: uuid.UUID, owner_id: uuid.UUID, *, abort: bool
    ) -> FocusSessionResult:
        async with self._uow_factory() as uow:
            focus = await uow.focus_sessions.get(focus_id)
            if focus is None or focus.owner_id != owner_id:
                raise ResourceNotFound("专注会话不存在")
            at = self._clock.now()
            if abort:
                focus.abort(at=at)
            else:
                focus.complete(at=at)
            await uow.focus_sessions.save(focus)
            await uow.commit()
        return _focus_result(focus)

    # --- 时间记录 + 周复盘 --------------------------------------------------

    async def log_time(
        self,
        *,
        owner_id: uuid.UUID,
        category: str,
        minutes: int,
        logged_date: date,
        ref_task_id: uuid.UUID | None = None,
    ) -> TimeLogResult:
        log = TimeLog.create(
            log_id=self._identifiers.new_id(),
            owner_id=owner_id,
            category=category,
            minutes=minutes,
            logged_date=logged_date,
            ref_task_id=ref_task_id,
            created_at=self._clock.now(),
        )
        async with self._uow_factory() as uow:
            await uow.time_logs.add(log)
            await uow.commit()
        return _log_result(log)

    async def weekly_review(
        self, *, owner_id: uuid.UUID, in_week_of: date
    ) -> WeeklyReviewResult:
        """聚合 in_week_of 所在自然周（周一~周日）本人各分类耗时。

        ponytail: 先按 category 求和的周报，可视化延后。
        """
        week_start = in_week_of - timedelta(days=in_week_of.weekday())
        week_end = week_start + timedelta(days=6)
        async with self._uow_factory() as uow:
            logs = await uow.time_logs.list_for_owner_between(
                owner_id=owner_id, start=week_start, end=week_end
            )
        totals: dict[str, int] = defaultdict(int)
        for log in logs:
            totals[log.category] += log.minutes
        by_category = tuple(
            CategorySummary(category=cat, total_minutes=mins)
            for cat, mins in sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))
        )
        return WeeklyReviewResult(
            owner_id=owner_id,
            week_start=week_start,
            week_end=week_end,
            total_minutes=sum(totals.values()),
            by_category=by_category,
        )

    @staticmethod
    async def _load_schedule(
        uow: TimeManagementUnitOfWork, schedule_id: uuid.UUID, owner_id: uuid.UUID
    ) -> Schedule:
        schedule = await uow.schedules.get(schedule_id)
        if schedule is None or schedule.owner_id != owner_id:
            raise ResourceNotFound("日程不存在")
        return schedule
