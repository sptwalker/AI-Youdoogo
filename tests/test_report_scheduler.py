"""定时报告调度器单测（离线）：纯 is_due 到点判定矩阵 + scan_once 发起/标记/跳过。

红线不旁路：系统发起复用 plan_work → start_workflow 同一入口（operator_id=None、原样透传
request），scan_once 从不自行构造步骤或触碰 is_red_line——对外步骤的 waiting_human 停点由
start_workflow/engine 保证，已被 test_durable_workflow 覆盖。本文件全程 mock，不触真实编排/数据库。
"""

import uuid
from datetime import datetime
from typing import Any

import pytest

from app.bootstrap import report_scheduler
from app.contexts.foundations.execution.report_scheduling import public as report_scheduling
from app.contexts.foundations.execution.report_scheduling.contracts import ScheduleView
from app.contexts.foundations.execution.workflow_templating.contracts import ResolvedStep


def _view(**overrides: Any) -> ScheduleView:
    base: dict[str, Any] = {
        "id": uuid.uuid4(),
        "name": "月度经营报告",
        "title": "月度经营报告",
        "request_text": "汇总本月经营数据并推送运营负责人审核",
        "creator_id": uuid.uuid4(),
        "assignee_agent_id": None,
        "template_id": None,
        "day_of_month": 1,
        "hour": 9,
        "enabled": True,
        "last_fired_period": None,
    }
    base.update(overrides)
    return ScheduleView(**base)


class _FakeSession:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


class _FakeSessions:
    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    def __call__(self) -> "_FakeSessions":
        return self

    async def __aenter__(self) -> _FakeSession:
        return self._session

    async def __aexit__(self, *exc: object) -> bool:
        return False


class _FakeStart:
    """捕获 start 调用的假发起器；证明系统发起走同一守卫入口。"""

    def __init__(self, result: dict[str, Any] | None) -> None:
        self.result = result
        self.calls: list[dict[str, Any]] = []

    async def __call__(
        self,
        session: object,
        request: str,
        *,
        creator_id: uuid.UUID,
        assignee_agent_id: uuid.UUID | None,
        operator_id: uuid.UUID | None,
        title: str | None,
        steps: list[Any] | None = None,
    ) -> dict[str, Any] | None:
        self.calls.append(
            {
                "request": request,
                "creator_id": creator_id,
                "assignee_agent_id": assignee_agent_id,
                "operator_id": operator_id,
                "title": title,
                "steps": steps,
            }
        )
        return self.result


def _patch_repo(
    monkeypatch: pytest.MonkeyPatch,
    *,
    views: list[ScheduleView],
    marked: list[tuple[uuid.UUID, str]],
) -> None:
    async def _list(_session: object) -> list[ScheduleView]:
        return views

    async def _mark(_session: object, schedule_id: uuid.UUID, period: str) -> None:
        marked.append((schedule_id, period))

    monkeypatch.setattr(report_scheduling, "list_enabled", _list)
    monkeypatch.setattr(report_scheduling, "mark_fired", _mark)


# ── is_due / current_period（纯函数，零外部调用）─────────────
def test_current_period_format() -> None:
    assert report_scheduler.current_period(datetime(2026, 8, 4, 10)) == "2026-08"


def test_is_due_true_at_or_after_target() -> None:
    at = report_scheduler.is_due(
        enabled=True, day_of_month=1, hour=9, last_fired_period=None, now=datetime(2026, 8, 1, 9)
    )
    later = report_scheduler.is_due(
        enabled=True, day_of_month=1, hour=9, last_fired_period=None, now=datetime(2026, 8, 15, 0)
    )
    assert at is True
    assert later is True


def test_is_due_false_before_target() -> None:
    same_day = report_scheduler.is_due(
        enabled=True, day_of_month=15, hour=9, last_fired_period=None, now=datetime(2026, 8, 15, 8)
    )
    day_before = report_scheduler.is_due(
        enabled=True, day_of_month=15, hour=9, last_fired_period=None, now=datetime(2026, 8, 14, 23)
    )
    assert same_day is False
    assert day_before is False


def test_is_due_false_when_disabled() -> None:
    due = report_scheduler.is_due(
        enabled=False,
        day_of_month=1,
        hour=0,
        last_fired_period=None,
        now=datetime(2026, 8, 1, 0),
    )
    assert due is False


def test_is_due_false_when_already_fired_this_period() -> None:
    assert (
        report_scheduler.is_due(
            enabled=True,
            day_of_month=1,
            hour=9,
            last_fired_period="2026-08",
            now=datetime(2026, 8, 20, 9),
        )
        is False
    )


def test_is_due_clamps_day_past_month_end() -> None:
    # 2026-02 只有 28 天；day_of_month=31 → clamp 到 28，28 号照样触发（不静默漏发）。
    due = report_scheduler.is_due(
        enabled=True,
        day_of_month=31,
        hour=0,
        last_fired_period=None,
        now=datetime(2026, 2, 28, 0),
    )
    assert due is True


# ── scan_once（发起 / 标记 / 跳过）──────────────────────────
async def test_scan_once_fires_and_marks(monkeypatch: pytest.MonkeyPatch) -> None:
    view = _view()
    marked: list[tuple[uuid.UUID, str]] = []
    _patch_repo(monkeypatch, views=[view], marked=marked)
    start = _FakeStart({"run": "ok"})
    session = _FakeSession()

    fired = await report_scheduler.scan_once(
        datetime(2026, 8, 1, 9), sessions=_FakeSessions(session), start=start
    )

    assert fired == 1
    assert len(start.calls) == 1
    call = start.calls[0]
    assert call["request"] == view.request_text  # 原样透传，不自行构造步骤
    assert call["creator_id"] == view.creator_id
    assert call["operator_id"] is None  # 红线不旁路：系统发起仍无 operator
    assert marked == [(view.id, "2026-08")]
    assert session.commits == 1


async def test_scan_once_skips_not_due(monkeypatch: pytest.MonkeyPatch) -> None:
    view = _view(day_of_month=15, hour=9)
    marked: list[tuple[uuid.UUID, str]] = []
    _patch_repo(monkeypatch, views=[view], marked=marked)
    start = _FakeStart({"run": "ok"})

    fired = await report_scheduler.scan_once(
        datetime(2026, 8, 15, 8), sessions=_FakeSessions(_FakeSession()), start=start
    )

    assert fired == 0
    assert start.calls == []
    assert marked == []


async def test_scan_once_skips_without_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    view = _view(creator_id=None)
    marked: list[tuple[uuid.UUID, str]] = []
    _patch_repo(monkeypatch, views=[view], marked=marked)
    start = _FakeStart({"run": "ok"})

    fired = await report_scheduler.scan_once(
        datetime(2026, 8, 1, 9), sessions=_FakeSessions(_FakeSession()), start=start
    )

    assert fired == 0
    assert start.calls == []  # 未配置负责人 → 不发起（红线审核人缺失）
    assert marked == []


async def test_scan_once_does_not_mark_when_start_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    view = _view()
    marked: list[tuple[uuid.UUID, str]] = []
    _patch_repo(monkeypatch, views=[view], marked=marked)
    start = _FakeStart(None)  # 规划失败/异常 → start 已回滚并返 None
    session = _FakeSession()

    fired = await report_scheduler.scan_once(
        datetime(2026, 8, 1, 9), sessions=_FakeSessions(session), start=start
    )

    assert fired == 0
    assert len(start.calls) == 1  # 确实尝试了发起
    assert marked == []  # 但未标记 → 下轮重试（漏发比重复更糟）
    assert session.commits == 0


# ── scan_once 模板分支（docs/25 P4：有模板走确定性展开，逐步派 6 部门）──────────
async def test_scan_once_template_expands_to_per_step_experts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """有 template_id → 载模板展开成钉死步骤，逐步带各自 expert（跳过 LLM）。"""
    tid = uuid.uuid4()
    view = _view(template_id=tid)
    marked: list[tuple[uuid.UUID, str]] = []
    _patch_repo(monkeypatch, views=[view], marked=marked)
    sales, finance = uuid.uuid4(), uuid.uuid4()
    resolved = [
        ResolvedStep(0, "取销售", "data_query", "查销售", (), sales),
        ResolvedStep(1, "取财务", "data_query", "查财务", (), finance),
    ]

    async def _load(_session: object, template_id: uuid.UUID) -> list[ResolvedStep]:
        assert template_id == tid
        return resolved

    monkeypatch.setattr(report_scheduler.workflow_templating, "load_template_steps", _load)
    start = _FakeStart({"run": "ok"})

    fired = await report_scheduler.scan_once(
        datetime(2026, 8, 1, 9), sessions=_FakeSessions(_FakeSession()), start=start
    )

    assert fired == 1
    passed = start.calls[0]["steps"]
    assert passed is not None  # 模板路径必带钉死步骤
    assert [step.assignee_expert_id for step in passed] == [sales, finance]  # 逐步派不同部门
    assert marked == [(view.id, "2026-08")]


async def test_scan_once_skips_when_template_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """指向的模板不存在/停用 → 跳过（不静默退化为单派发 LLM 串跑）。"""
    view = _view(template_id=uuid.uuid4())
    marked: list[tuple[uuid.UUID, str]] = []
    _patch_repo(monkeypatch, views=[view], marked=marked)

    async def _load(_session: object, _template_id: uuid.UUID) -> None:
        return None

    monkeypatch.setattr(report_scheduler.workflow_templating, "load_template_steps", _load)
    start = _FakeStart({"run": "ok"})

    fired = await report_scheduler.scan_once(
        datetime(2026, 8, 1, 9), sessions=_FakeSessions(_FakeSession()), start=start
    )

    assert fired == 0
    assert start.calls == []  # 模板失效即不发起
    assert marked == []
