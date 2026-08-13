"""营销舆情触发中枢单测（离线、全 mock）：命中发事件 / 无命中不发 / handler 忠实发起 / 畸形跳过。

红线不旁路：handler 走 report_scheduler._start_workflow 同一入口（operator_id=None、原样透传
request、steps 来自种子模板），从不自行构造步骤或触碰 is_red_line——feishu_notify_person 对外步骤的
waiting_human 停点由 start()/engine 保证（已被 test_durable_workflow 覆盖）。
"""

import uuid
from typing import Any

import pytest

from app.bootstrap import sentiment_scanner
from app.contexts.business.marketing_sentiment.public import (
    SentimentSignal,
    SentimentThresholds,
)
from app.contexts.foundations.execution.workflow_templating.contracts import (
    TemplateStep,
    WorkflowTemplateView,
)

_TH = SentimentThresholds(
    negative_ratio_jump=0.2, negative_ratio_floor=0.3, competitor_major=True, policy_change=True
)


class _FakeSession:
    pass


class _FakeEvent:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.id = uuid.uuid4()
        self.payload = payload


class _FakeStart:
    """捕获 start 调用，证明系统发起走同一守卫入口。"""

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


# ── scan_sentiment_once：命中发事件 / 无命中不发 ──────────────
async def test_scan_emits_when_hit() -> None:
    captured: dict[str, Any] = {}

    async def _emit(session: object, **kwargs: Any) -> object:
        captured.update(kwargs)
        return object()

    sig = SentimentSignal("电商评论", "negative_ratio", "差评集中",
                          negative_ratio=0.6, baseline_ratio=0.3)
    creator = uuid.uuid4()
    count = await sentiment_scanner.scan_sentiment_once(
        _FakeSession(), signals=[sig], creator_id=creator, window_key="2026-08-04T10",
        thresholds=_TH, emit=_emit,
    )

    assert count == 1
    assert captured["creator_id"] == creator
    assert captured["window_key"] == "2026-08-04T10"
    assert [a.kind for a in captured["alerts"]] == ["negative_spike"]


async def test_scan_no_emit_when_no_hit() -> None:
    calls = 0

    async def _emit(session: object, **kwargs: Any) -> object:
        nonlocal calls
        calls += 1
        return object()

    sig = SentimentSignal("社媒", "negative_ratio", "小幅", negative_ratio=0.35, baseline_ratio=0.3)
    count = await sentiment_scanner.scan_sentiment_once(
        _FakeSession(), signals=[sig], creator_id=uuid.uuid4(), window_key="w",
        thresholds=_TH, emit=_emit,
    )

    assert count == 0
    assert calls == 0  # 无命中 → 不发事件（下游据此不起 workflow）


# ── handle_sentiment_anomaly：忠实发起 / 畸形跳过 / 模板缺失抛 ──
async def test_handler_starts_workflow_with_template(monkeypatch: pytest.MonkeyPatch) -> None:
    creator, assignee = uuid.uuid4(), uuid.uuid4()
    sentinel_steps = [object(), object()]

    async def _steps(_session: object) -> list[Any]:
        return sentinel_steps

    monkeypatch.setattr(sentiment_scanner, "_seed_template_steps", _steps)
    start = _FakeStart({"run": "ok"})
    event = _FakeEvent(
        {
            "creator_id": str(creator),
            "assignee_agent_id": str(assignee),
            "title": "营销舆情应急响应",
            "request_text": "检测到营销舆情异常：电商评论 负面占比 60%",
        }
    )

    await sentiment_scanner.handle_sentiment_anomaly(_FakeSession(), event, start=start)

    assert len(start.calls) == 1
    call = start.calls[0]
    assert call["creator_id"] == creator
    assert call["assignee_agent_id"] == assignee
    assert call["operator_id"] is None  # 红线不旁路：系统发起无 operator
    assert call["request"] == "检测到营销舆情异常：电商评论 负面占比 60%"  # 原样透传
    assert call["steps"] is sentinel_steps  # 钉死步骤来自种子模板，不自构造


async def test_handler_skips_when_creator_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _steps(_session: object) -> list[Any]:
        raise AssertionError("creator 缺失时不应展开模板")

    monkeypatch.setattr(sentiment_scanner, "_seed_template_steps", _steps)
    start = _FakeStart({"run": "ok"})
    event = _FakeEvent({"request_text": "x", "assignee_agent_id": None})

    await sentiment_scanner.handle_sentiment_anomaly(_FakeSession(), event, start=start)

    assert start.calls == []  # 畸形事件（无红线审核人）→ 跳过，不发起


async def test_handler_raises_when_template_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _steps(_session: object) -> None:
        return None

    monkeypatch.setattr(sentiment_scanner, "_seed_template_steps", _steps)
    start = _FakeStart({"run": "ok"})
    event = _FakeEvent({"creator_id": str(uuid.uuid4()), "request_text": "x"})

    with pytest.raises(RuntimeError):  # 模板缺失 → 抛，让 outbox 重试到 terminal（暴露给运维）
        await sentiment_scanner.handle_sentiment_anomaly(_FakeSession(), event, start=start)
    assert start.calls == []


async def test_handler_raises_when_start_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _steps(_session: object) -> list[Any]:
        return [object()]

    monkeypatch.setattr(sentiment_scanner, "_seed_template_steps", _steps)
    start = _FakeStart(None)  # 规划失败/异常回滚
    event = _FakeEvent({"creator_id": str(uuid.uuid4()), "request_text": "x"})

    with pytest.raises(RuntimeError):
        await sentiment_scanner.handle_sentiment_anomaly(_FakeSession(), event, start=start)


# ── _seed_template_steps：按名匹配 enabled 模板 ───────────────
async def test_seed_template_matches_by_name(monkeypatch: pytest.MonkeyPatch) -> None:
    tid = uuid.uuid4()
    step = TemplateStep(0, "取舆情", "data_query", "查", (), "dir_marketing")
    views = [
        WorkflowTemplateView(id=uuid.uuid4(), name="别的模板", steps=(step,)),
        WorkflowTemplateView(id=tid, name=sentiment_scanner.SENTIMENT_TEMPLATE_NAME, steps=(step,)),
    ]

    async def _list_enabled(_session: object) -> list[WorkflowTemplateView]:
        return views

    async def _template_steps(_session: object, template_id: uuid.UUID) -> list[Any]:
        assert template_id == tid  # 只对匹配名的那张展开
        return ["expanded"]

    monkeypatch.setattr(sentiment_scanner.workflow_templating, "list_enabled", _list_enabled)
    monkeypatch.setattr(sentiment_scanner, "_template_plan_steps", _template_steps)

    result = await sentiment_scanner._seed_template_steps(_FakeSession())
    assert result == ["expanded"]


async def test_seed_template_none_when_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _list_enabled(_session: object) -> list[WorkflowTemplateView]:
        return []

    monkeypatch.setattr(sentiment_scanner.workflow_templating, "list_enabled", _list_enabled)
    assert await sentiment_scanner._seed_template_steps(_FakeSession()) is None
