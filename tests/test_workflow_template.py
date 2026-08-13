"""工作流模板底座单测（docs/25 P4）：纯展开 code→id、repo 往返、roster 解析、public 端到端、
_start_workflow(steps=) 跳过 LLM 规划器并把逐步 expert 钉进启动命令。全程 sqlite/mock，不触共享
PG、不触真实编排。
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.bootstrap import report_scheduler
from app.contexts.foundations.execution.work_planning import public as work_planning
from app.contexts.foundations.execution.workflow_templating import public as templating
from app.contexts.foundations.execution.workflow_templating.application.expansion import (
    expand_template,
)
from app.contexts.foundations.execution.workflow_templating.contracts import (
    TemplateStep,
    WorkflowTemplateView,
)
from app.contexts.foundations.execution.workflow_templating.infrastructure import (
    repository,
    roster,
)
from app.models import Base
from app.models.agent import AgentRole
from app.models.workflow_template import WorkflowTemplate


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        yield db
    await engine.dispose()


# ── expand_template（纯逻辑，不读 DB）────────────────────────
def test_expand_resolves_code_and_falls_back() -> None:
    """expert_code→id 解析；未知/缺失 code→None 回落；保序 + depends 透传。"""
    mid = uuid.uuid4()
    view = WorkflowTemplateView(
        id=uuid.uuid4(),
        name="月报",
        steps=(
            TemplateStep(0, "取销售", "data_query", "查", (), "dir_marketing"),
            TemplateStep(1, "取未知", "data_query", "查", (), "dir_missing"),
            TemplateStep(2, "汇总", "deliver", "汇", (0, 1), None),
        ),
    )
    resolved = expand_template(view, {"dir_marketing": mid}.get)

    assert [step.no for step in resolved] == [0, 1, 2]  # 保序
    assert resolved[0].assignee_expert_id == mid  # code→id
    assert resolved[1].assignee_expert_id is None  # 未知 code 回落
    assert resolved[2].assignee_expert_id is None  # 无 code 回落
    assert resolved[2].depends_on == (0, 1)  # 依赖透传


# ── repository（单写者往返）─────────────────────────────────
async def test_repo_roundtrip_and_disabled_hidden(session: AsyncSession) -> None:
    enabled = WorkflowTemplate(
        name="月报",
        steps=[{"no": 0, "title": "t", "skill": "data_query", "instruction": "i",
                "depends_on": [], "expert_code": "dir_marketing"}],
        enabled=True,
    )
    disabled = WorkflowTemplate(name="停用模板", steps=[], enabled=False)
    session.add_all([enabled, disabled])
    await session.commit()

    view = await repository.get(session, enabled.id)
    assert view is not None
    assert view.name == "月报"
    assert view.steps[0].expert_code == "dir_marketing"
    assert view.steps[0].depends_on == ()

    assert await repository.get(session, disabled.id) is None  # 停用不可见
    assert await repository.get(session, uuid.uuid4()) is None  # 不存在

    listed = await repository.list_enabled(session)
    assert [v.name for v in listed] == ["月报"]  # 只列启用中的


# ── roster（code→id 批解析，跳过停用）───────────────────────
async def test_roster_resolves_active_only(session: AsyncSession) -> None:
    active = AgentRole(name="销售总监", prompt_template="p", code="dir_marketing", is_active=True)
    inactive = AgentRole(name="停用总监", prompt_template="p", code="dir_off", is_active=False)
    session.add_all([active, inactive])
    await session.commit()

    resolved = await roster.load_agent_ids(session, ["dir_marketing", "dir_off", "dir_missing"])
    assert resolved == {"dir_marketing": active.id}  # 仅启用 code 入表


# ── public.load_template_steps（端到端展开）─────────────────
async def test_public_load_template_steps_end_to_end(session: AsyncSession) -> None:
    sales = AgentRole(name="销售总监", prompt_template="p", code="dir_marketing", is_active=True)
    session.add(sales)
    template = WorkflowTemplate(
        name="月报",
        steps=[
            {"no": 0, "title": "取销售", "skill": "data_query", "instruction": "查",
             "depends_on": [], "expert_code": "dir_marketing"},
            {"no": 1, "title": "取未知", "skill": "data_query", "instruction": "查",
             "depends_on": [], "expert_code": "dir_missing"},
        ],
        enabled=True,
    )
    session.add(template)
    await session.commit()

    resolved = await templating.load_template_steps(session, template.id)
    assert resolved is not None
    assert resolved[0].assignee_expert_id == sales.id  # 真实 code→id
    assert resolved[1].assignee_expert_id is None  # 未知 code 回落
    assert await templating.load_template_steps(session, uuid.uuid4()) is None  # 无模板


# ── _start_workflow(steps=) 跳过 LLM 规划器 ─────────────────
async def test_start_with_steps_skips_planner(monkeypatch: pytest.MonkeyPatch) -> None:
    """给了 steps → 不调 plan_work（LLM），确定性建 WorkflowPlan、逐步 expert 钉进启动命令。"""
    plan_calls = {"n": 0}

    async def _plan(_request: object) -> Any:  # pragma: no cover - 断言其从未被调
        plan_calls["n"] += 1
        raise AssertionError("模板路径不应触碰 LLM 规划器")

    captured: dict[str, Any] = {}

    class _FakeStarted:
        parent_task_id = uuid.uuid4()

    async def _start_workflow(_session: object, command: Any) -> _FakeStarted:
        captured["command"] = command
        return _FakeStarted()

    monkeypatch.setattr(report_scheduler.work_planning, "plan_work", _plan)
    monkeypatch.setattr(report_scheduler.task_management, "start_workflow", _start_workflow)

    sales = uuid.uuid4()
    steps = [
        work_planning.WorkflowPlanStep(
            number=0, title="取销售", capability_key="data_query", instruction="查",
            depends_on=(), assignee_expert_id=sales,
        ),
        work_planning.WorkflowPlanStep(
            number=1, title="汇总", capability_key="deliver", instruction="汇",
            depends_on=(0,), assignee_expert_id=None,
        ),
    ]

    class _FakeDB:
        async def rollback(self) -> None: ...

    result = await report_scheduler._start_workflow(
        _FakeDB(),
        "月度经营报告请求正文",
        creator_id=uuid.uuid4(),
        assignee_agent_id=None,
        operator_id=None,
        title="月报",
        steps=steps,
    )

    assert result == {"parent_task_id": str(_FakeStarted.parent_task_id)}
    assert plan_calls["n"] == 0  # 规划器一次都没调
    command = captured["command"]
    assert [step.assignee_expert_id for step in command.steps] == [sales, None]  # 逐步 expert 透传
