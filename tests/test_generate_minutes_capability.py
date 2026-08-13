"""机械纪要步（generate_minutes）单测（离线）——读上游会议 artifact 机械生成纪要：
- _meeting_artifact：从上游 pipe_outputs 流入的 artifacts 取 kind==meeting 且带 meeting_id 的项。
- _LegacyCapabilityExecutionAdapter.generate_minutes 分支：读**上游真 meeting_id** 调
  meeting_management.public.generate_minutes（绝不自写 meeting ORM，保持单一写者）；无发言
  （RuleViolation）如实跳过、无上游会议跳过——均不判失败、不触发重试。
- 注册表成员：机械·不可见（无 executor_factory/legacy_executor）·进 MECHANICAL+AUTOMATIC。
全程 mock，不触真实 DB/会议。

★dev 架构：convene 机械发布步把真会议记为 kind=meeting 的 **artifact**（非 dataset），本步依赖已由
policies.pair_publish_steps repoint 指向该发布步；本步不再回吐数据集（send_email 直接 repoint 到
convene 发布步取与会人，纪要不喂下游）。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.agents.skill_registry import REGISTRY, enabled_skills
from app.contexts.business.meeting_management import public as meetings
from app.contexts.foundations.execution.workflow_runtime.contracts.runtime import (
    ClaimedWorkflowStep,
    PreparedWorkflowStep,
)
from app.contexts.foundations.execution.workflow_runtime.domain.policies import (
    AUTOMATIC_CAPABILITIES,
    MECHANICAL_CAPABILITIES,
    requires_human_review,
)
from app.contexts.foundations.execution.workflow_runtime.infrastructure.legacy_execution import (
    _LegacyCapabilityExecutionAdapter,
    _meeting_artifact,
)
from app.contexts.shared_kernel import RuleViolation
from app.models.agent import AgentRole


def _role() -> AgentRole:
    return AgentRole(id=uuid.uuid4(), name="纪要器", prompt_template="x", tools=[])


def _claim() -> ClaimedWorkflowStep:
    return ClaimedWorkflowStep(
        workflow_id=uuid.uuid4(),
        step_id=uuid.uuid4(),
        task_card_id=None,
        expert_id=None,
        worker_id="w",
        attempt=1,
        version=1,
        lease_until=datetime.now(UTC),
    )


def _prepared(
    input_data: tuple[tuple[str, object], ...], *, creator_id: uuid.UUID | None = None
) -> PreparedWorkflowStep:
    return PreparedWorkflowStep(
        claim=_claim(),
        trace_id=uuid.uuid4(),
        creator_id=creator_id or uuid.uuid4(),
        request_text="",
        title="生成纪要",
        capability_key="generate_minutes",
        instruction="",
        expert=None,
        input_data=input_data,
    )


def _meeting_art(meeting_id: uuid.UUID) -> dict[str, object]:
    return {"kind": "meeting", "meeting_id": str(meeting_id)}


def _adapter() -> _LegacyCapabilityExecutionAdapter:
    return _LegacyCapabilityExecutionAdapter(None, None)  # type: ignore[arg-type]


# ── _meeting_artifact：从上游 artifacts 取会议项 ─────────────────
def test_meeting_artifact_picks_meeting_item() -> None:
    mid = uuid.uuid4()
    input_data = (("artifacts", [{"kind": "other"}, _meeting_art(mid)]),)
    art = _meeting_artifact(input_data)
    assert art is not None and art["meeting_id"] == str(mid)


def test_meeting_artifact_none_when_absent() -> None:
    assert _meeting_artifact((("artifacts", [{"kind": "other"}]),)) is None
    assert _meeting_artifact((("datasets", [1]),)) is None
    assert _meeting_artifact(()) is None


# ── generate_minutes 机械步：读真 meeting_id 调 public.generate_minutes ──
async def test_generates_minutes_with_upstream_meeting_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mid = uuid.uuid4()
    creator = uuid.uuid4()
    calls: list[tuple[uuid.UUID, uuid.UUID | None]] = []

    async def _gen(db, meeting_id, *, operator_id=None):
        calls.append((meeting_id, operator_id))
        return object()

    monkeypatch.setattr(meetings, "generate_minutes", _gen)
    prepared = _prepared((("artifacts", [_meeting_art(mid)]),), creator_id=creator)
    res = await _adapter()._generate_minutes(prepared)

    assert res.succeeded
    # 用上游真 meeting_id + 本步 creator 作 operator 调单一写者
    assert calls == [(mid, creator)]
    assert str(mid) in res.content
    # dev 架构不回吐数据集（纪要不喂下游）
    assert res.datasets == ()


async def test_skips_when_meeting_has_no_discussion(monkeypatch: pytest.MonkeyPatch) -> None:
    """会议无发言 → RuleViolation 属正常前置缺失，如实声明、不判失败、不触发重试。"""
    mid = uuid.uuid4()

    async def _gen(db, meeting_id, *, operator_id=None):
        raise RuleViolation("会议暂无发言，无法生成纪要")

    monkeypatch.setattr(meetings, "generate_minutes", _gen)
    res = await _adapter()._generate_minutes(_prepared((("artifacts", [_meeting_art(mid)]),)))
    assert res.succeeded and "跳过" in res.content


async def test_skips_when_no_upstream_meeting(monkeypatch: pytest.MonkeyPatch) -> None:
    called = False

    async def _gen(db, meeting_id, *, operator_id=None):
        nonlocal called
        called = True
        return object()

    monkeypatch.setattr(meetings, "generate_minutes", _gen)
    res = await _adapter()._generate_minutes(_prepared((("artifacts", [{"kind": "docx"}]),)))
    assert res.succeeded and "跳过" in res.content
    assert called is False


# ── 注册表成员：机械·不可见·进 MECHANICAL+AUTOMATIC ──────────────
def test_registry_membership_mechanical_and_invisible() -> None:
    assert "generate_minutes" in REGISTRY
    skill = REGISTRY["generate_minutes"]
    # 无 executor_factory（不经 ToolDispatcher，由机械适配器专列分支处理）、无 legacy_executor
    assert skill.executor_factory is None
    assert skill.legacy_executor is None
    assert skill.default_on is False  # 对规划器/对话不可见、不进默认启用集
    keys = {s.key for s in enabled_skills(_role())}  # tools=[] → 仅默认集
    assert "generate_minutes" not in keys
    assert "generate_minutes" in MECHANICAL_CAPABILITIES
    assert "generate_minutes" in AUTOMATIC_CAPABILITIES
    assert requires_human_review("generate_minutes") is False
