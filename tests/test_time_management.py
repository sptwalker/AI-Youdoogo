"""Time Management 单测（离线，Fake 仓储/UoW，无 DB）。

覆盖：三聚合领域不变量、CRUD、行级隔离（他人当作不存在）、智能排程只出建议 + confirm 才生效、
番茄钟 start/complete/abort + 单点通知拦截、周复盘跨周聚合、固定规则排程算法。
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest

from app.contexts.business.time_management.application.contracts import CategorySummary
from app.contexts.business.time_management.application.use_cases import (
    TimeManagementApplication,
)
from app.contexts.business.time_management.domain.models import (
    CONFIRMED,
    FOCUS_ABORTED,
    FOCUS_COMPLETED,
    SUGGESTED,
    FocusSession,
    PlannableItem,
    Schedule,
    TimeLog,
    plan_suggestions,
)
from app.contexts.shared_kernel import ResourceNotFound, RuleViolation

_OWNER = uuid.UUID("11111111-1111-1111-1111-111111111111")
_OTHER = uuid.UUID("22222222-2222-2222-2222-222222222222")


class _FakeScheduleRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Schedule] = {}

    async def add(self, schedule: Schedule) -> None:
        self.rows[schedule.id] = schedule

    async def get(self, schedule_id: uuid.UUID) -> Schedule | None:
        return self.rows.get(schedule_id)

    async def save(self, schedule: Schedule) -> None:
        self.rows[schedule.id] = schedule

    async def list_for_owner(
        self, *, owner_id: uuid.UUID, status: str | None, limit: int
    ) -> tuple[Schedule, ...]:
        rows = [
            s
            for s in self.rows.values()
            if s.owner_id == owner_id and (status is None or s.status == status)
        ]
        return tuple(rows[:limit])


class _FakeFocusRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, FocusSession] = {}

    async def add(self, focus: FocusSession) -> None:
        self.rows[focus.id] = focus

    async def get(self, focus_id: uuid.UUID) -> FocusSession | None:
        return self.rows.get(focus_id)

    async def save(self, focus: FocusSession) -> None:
        self.rows[focus.id] = focus

    async def active_for_owner(self, owner_id: uuid.UUID) -> FocusSession | None:
        for focus in self.rows.values():
            if focus.owner_id == owner_id and focus.status == "active":
                return focus
        return None


class _FakeTimeLogRepo:
    def __init__(self) -> None:
        self.rows: list[TimeLog] = []

    async def add(self, log: TimeLog) -> None:
        self.rows.append(log)

    async def list_for_owner_between(
        self, *, owner_id: uuid.UUID, start: date, end: date
    ) -> tuple[TimeLog, ...]:
        return tuple(
            log
            for log in self.rows
            if log.owner_id == owner_id and start <= log.logged_date <= end
        )


class _FakeUnitOfWork:
    def __init__(
        self,
        schedules: _FakeScheduleRepo,
        focus_sessions: _FakeFocusRepo,
        time_logs: _FakeTimeLogRepo,
    ) -> None:
        self.schedules = schedules
        self.focus_sessions = focus_sessions
        self.time_logs = time_logs
        self.commits = 0

    async def __aenter__(self) -> _FakeUnitOfWork:
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        return None


class _StaticClock:
    def __init__(self, moment: datetime) -> None:
        self._moment = moment

    def now(self) -> datetime:
        return self._moment


class _SequenceIdentifiers:
    def __init__(self) -> None:
        self._n = 0

    def new_id(self) -> uuid.UUID:
        self._n += 1
        return uuid.UUID(int=self._n)


def _application() -> TimeManagementApplication:
    schedules, focus, logs = _FakeScheduleRepo(), _FakeFocusRepo(), _FakeTimeLogRepo()

    def _factory() -> _FakeUnitOfWork:
        return _FakeUnitOfWork(schedules, focus, logs)

    return TimeManagementApplication(
        uow_factory=_factory,
        clock=_StaticClock(datetime(2026, 8, 17, 9, tzinfo=UTC)),  # 周一
        identifiers=_SequenceIdentifiers(),
    )


# ── 领域不变量 ───────────────────────────────────────────
def test_schedule_rejects_bad_window() -> None:
    with pytest.raises(RuleViolation):
        Schedule.create_manual(
            schedule_id=uuid.uuid4(),
            owner_id=_OWNER,
            title="会议",
            start_at=datetime(2026, 8, 17, 10, tzinfo=UTC),
            end_at=datetime(2026, 8, 17, 9, tzinfo=UTC),
            linked_task_id=None,
            created_at=datetime(2026, 8, 17, tzinfo=UTC),
        )


def test_confirm_only_suggested() -> None:
    manual = Schedule.create_manual(
        schedule_id=uuid.uuid4(),
        owner_id=_OWNER,
        title="会议",
        start_at=datetime(2026, 8, 17, 9, tzinfo=UTC),
        end_at=datetime(2026, 8, 17, 10, tzinfo=UTC),
        linked_task_id=None,
        created_at=datetime(2026, 8, 17, tzinfo=UTC),
    )
    with pytest.raises(RuleViolation):
        manual.confirm()  # 已 confirmed，不可再 confirm


def test_focus_double_end_rejected() -> None:
    focus = FocusSession.start(
        focus_id=uuid.uuid4(),
        owner_id=_OWNER,
        planned_minutes=25,
        intercept_notifications=True,
        started_at=datetime(2026, 8, 17, 9, tzinfo=UTC),
    )
    focus.complete(at=datetime(2026, 8, 17, 9, 25, tzinfo=UTC))
    with pytest.raises(RuleViolation):
        focus.abort(at=datetime(2026, 8, 17, 9, 30, tzinfo=UTC))


def test_timelog_rejects_nonpositive() -> None:
    with pytest.raises(RuleViolation):
        TimeLog.create(
            log_id=uuid.uuid4(),
            owner_id=_OWNER,
            category="开发",
            minutes=0,
            logged_date=date(2026, 8, 17),
            ref_task_id=None,
            created_at=datetime(2026, 8, 17, tzinfo=UTC),
        )


# ── 日程用例 + 隔离 ──────────────────────────────────────
async def test_create_schedule_confirmed() -> None:
    app = _application()
    result = await app.create_schedule(
        owner_id=_OWNER,
        title="季度评审",
        start_at=datetime(2026, 8, 17, 9, tzinfo=UTC),
        end_at=datetime(2026, 8, 17, 10, tzinfo=UTC),
    )
    assert result.status == CONFIRMED and result.source == "manual"


async def test_confirm_isolates_by_owner() -> None:
    app = _application()
    suggestions = await app.suggest_schedules(
        owner_id=_OWNER,
        items=[
            PlannableItem(
                ref_task_id=uuid.uuid4(),
                title="写周报",
                priority=1,
                duration_minutes=60,
                due_at=None,
            )
        ],
        window_start=datetime(2026, 8, 17, 9, tzinfo=UTC),
        window_end=datetime(2026, 8, 17, 18, tzinfo=UTC),
    )
    assert len(suggestions) == 1 and suggestions[0].status == SUGGESTED
    # 他人不能 confirm 我的建议 → 当作不存在
    with pytest.raises(ResourceNotFound):
        await app.confirm_schedule(suggestions[0].id, owner_id=_OTHER)
    confirmed = await app.confirm_schedule(suggestions[0].id, owner_id=_OWNER)
    assert confirmed.status == CONFIRMED


async def test_suggestion_not_effective_until_confirmed() -> None:
    app = _application()
    await app.suggest_schedules(
        owner_id=_OWNER,
        items=[
            PlannableItem(
                ref_task_id=uuid.uuid4(),
                title="任务",
                priority=1,
                duration_minutes=30,
                due_at=None,
            )
        ],
        window_start=datetime(2026, 8, 17, 9, tzinfo=UTC),
        window_end=datetime(2026, 8, 17, 18, tzinfo=UTC),
    )
    # 建议态不视为已生效：查 confirmed 应为空
    effective = await app.list_schedules(owner_id=_OWNER, status=CONFIRMED)
    assert effective == ()


# ── 专注番茄钟 + 拦截判定 ────────────────────────────────
async def test_focus_lifecycle_and_intercept_flag() -> None:
    app = _application()
    started = await app.start_focus(owner_id=_OWNER, planned_minutes=25)
    assert await app.has_active_intercepting_focus(_OWNER) is True
    assert await app.has_active_intercepting_focus(_OTHER) is False  # 隔离
    completed = await app.complete_focus(started.id, owner_id=_OWNER)
    assert completed.status == FOCUS_COMPLETED
    assert await app.has_active_intercepting_focus(_OWNER) is False


async def test_focus_no_intercept_when_flag_off() -> None:
    app = _application()
    await app.start_focus(
        owner_id=_OWNER, planned_minutes=25, intercept_notifications=False
    )
    assert await app.has_active_intercepting_focus(_OWNER) is False


async def test_abort_focus_isolated() -> None:
    app = _application()
    started = await app.start_focus(owner_id=_OWNER, planned_minutes=25)
    with pytest.raises(ResourceNotFound):
        await app.abort_focus(started.id, owner_id=_OTHER)
    aborted = await app.abort_focus(started.id, owner_id=_OWNER)
    assert aborted.status == FOCUS_ABORTED


# ── 周复盘 ───────────────────────────────────────────────
async def test_weekly_review_sums_by_category_within_week() -> None:
    app = _application()
    # 本周（周一 8/17 ~ 周日 8/23）
    await app.log_time(
        owner_id=_OWNER, category="开发", minutes=120, logged_date=date(2026, 8, 17)
    )
    await app.log_time(
        owner_id=_OWNER, category="开发", minutes=60, logged_date=date(2026, 8, 19)
    )
    await app.log_time(
        owner_id=_OWNER, category="会议", minutes=30, logged_date=date(2026, 8, 23)
    )
    # 上周与下周各一条，须被排除
    await app.log_time(
        owner_id=_OWNER, category="开发", minutes=999, logged_date=date(2026, 8, 16)
    )
    await app.log_time(
        owner_id=_OWNER, category="开发", minutes=999, logged_date=date(2026, 8, 24)
    )
    # 他人一条，须被排除
    await app.log_time(
        owner_id=_OTHER, category="开发", minutes=500, logged_date=date(2026, 8, 18)
    )
    review = await app.weekly_review(owner_id=_OWNER, in_week_of=date(2026, 8, 20))
    assert review.week_start == date(2026, 8, 17)
    assert review.week_end == date(2026, 8, 23)
    assert review.total_minutes == 210
    assert review.by_category[0] == CategorySummary(category="开发", total_minutes=180)


# ── 固定规则排程算法 ─────────────────────────────────────
def test_plan_suggestions_fills_gaps_by_due_then_priority() -> None:
    day = datetime(2026, 8, 17, 9, tzinfo=UTC)
    busy = [(day + timedelta(hours=2), day + timedelta(hours=3))]  # 11:00-12:00 占用
    items = [
        PlannableItem(uuid.uuid4(), "低优无截止", 1, 60, None),
        PlannableItem(uuid.uuid4(), "有截止先排", 1, 60, day + timedelta(hours=1)),
    ]
    slots = plan_suggestions(
        items=items,
        busy=busy,
        window_start=day,
        window_end=day + timedelta(hours=8),
    )
    assert len(slots) == 2
    # 有截止的先排到最早空档 9:00-10:00
    assert slots[0].title == "有截止先排"
    assert slots[0].start_at == day
    # 第二个续排 10:00-11:00（不与 11:00 占用冲突）
    assert slots[1].start_at == day + timedelta(hours=1)
    assert slots[1].end_at == day + timedelta(hours=2)
