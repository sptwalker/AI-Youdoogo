"""任务编排 B.1 单测（docs/14 §4.2）:红线判定 + parse_plan 校验(纯函数) + build_steps DAG 建卡。

plan() 的 LLM 调用用 monkeypatch 打桩;parse_plan/is_red_line 是纯函数直接测。
"""

import json
import uuid
from collections.abc import AsyncGenerator
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import Base
from app.models.system import SysUser
from app.services import orchestration_service as orch
from app.services import task_service


@pytest.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


async def _creator(db: AsyncSession) -> uuid.UUID:
    u = SysUser(username=f"u{uuid.uuid4().hex[:6]}", password_hash="x", role_code="admin")
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u.id


def _plan_json(steps: list[dict[str, Any]], multi: bool = True) -> str:
    return json.dumps({"multi": multi, "steps": steps}, ensure_ascii=False)


# ── 红线判定 ────────────────────────────────────────────
def test_red_line_by_whitelist() -> None:
    assert orch.is_red_line("data_query") is False  # 只读取数=非红线
    assert orch.is_red_line("deliver") is False  # 交付文件=非红线
    assert orch.is_red_line("collab") is True  # 协作=红线
    assert orch.is_red_line("notify") is True  # 通知=红线
    assert orch.is_red_line("other") is True  # 未知=安全默认红线


# ── parse_plan 纯函数 ───────────────────────────────────
def test_parse_plan_valid_dag() -> None:
    raw = _plan_json([
        {"no": 0, "title": "取数", "skill": "data_query", "instruction": "查", "depends_on": []},
        {"no": 1, "title": "做报", "skill": "deliver", "instruction": "做", "depends_on": [0]},
    ])
    steps = orch.parse_plan(raw)
    assert steps is not None and len(steps) == 2
    assert steps[1].depends_on == [0] and steps[0].skill == "data_query"


def test_parse_plan_single_action_none() -> None:
    """multi=false → 不编排。"""
    assert orch.parse_plan(_plan_json([], multi=False)) is None


def test_parse_plan_less_than_two_steps_none() -> None:
    one = [{"no": 0, "title": "查", "skill": "data_query", "instruction": "x", "depends_on": []}]
    assert orch.parse_plan(_plan_json(one)) is None


def test_parse_plan_strips_code_fence() -> None:
    raw = "```json\n" + _plan_json([
        {"no": 0, "title": "a", "skill": "data_query", "instruction": "x", "depends_on": []},
        {"no": 1, "title": "b", "skill": "deliver", "instruction": "y", "depends_on": [0]},
    ]) + "\n```"
    assert orch.parse_plan(raw) is not None


def test_parse_plan_cycle_rejected() -> None:
    """0→1→0 成环 → None。"""
    raw = _plan_json([
        {"no": 0, "title": "a", "skill": "deliver", "instruction": "x", "depends_on": [1]},
        {"no": 1, "title": "b", "skill": "deliver", "instruction": "y", "depends_on": [0]},
    ])
    assert orch.parse_plan(raw) is None


def test_parse_plan_dangling_dep_rejected() -> None:
    """依赖不存在的 no → None。"""
    raw = _plan_json([
        {"no": 0, "title": "a", "skill": "deliver", "instruction": "x", "depends_on": []},
        {"no": 1, "title": "b", "skill": "deliver", "instruction": "y", "depends_on": [9]},
    ])
    assert orch.parse_plan(raw) is None


def test_parse_plan_duplicate_no_rejected() -> None:
    raw = _plan_json([
        {"no": 0, "title": "a", "skill": "deliver", "instruction": "x", "depends_on": []},
        {"no": 0, "title": "b", "skill": "deliver", "instruction": "y", "depends_on": []},
    ])
    assert orch.parse_plan(raw) is None


def test_parse_plan_garbage_none() -> None:
    assert orch.parse_plan("这不是JSON") is None
    assert orch.parse_plan("") is None


def test_parse_plan_caps_steps() -> None:
    """超过上限只取前 _MAX_STEPS（且截断后依赖仍需合法）。"""
    many = [{"no": i, "title": f"s{i}", "skill": "deliver", "instruction": "x",
             "depends_on": []} for i in range(20)]
    steps = orch.parse_plan(_plan_json(many))
    assert steps is not None and len(steps) == orch._MAX_STEPS


# ── plan() LLM 打桩 ─────────────────────────────────────
async def test_plan_returns_none_on_single(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _Reply:
        content = _plan_json([], multi=False)

    class _LLM:
        async def ainvoke(self, *a: Any, **k: Any) -> Any:
            return _Reply()

    monkeypatch.setattr(orch, "get_llm_for_role", lambda *a, **k: _LLM())
    assert await orch.plan(db, "今天天气如何") is None


async def test_plan_llm_error_returns_none(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _LLM:
        async def ainvoke(self, *a: Any, **k: Any) -> Any:
            raise RuntimeError("模型不可用")

    monkeypatch.setattr(orch, "get_llm_for_role", lambda *a, **k: _LLM())
    assert await orch.plan(db, "做个复合任务") is None  # 故障退回单步


# ── build_steps DAG 建卡 ────────────────────────────────
async def test_build_steps_creates_cards_and_wires_deps(db: AsyncSession) -> None:
    creator = await _creator(db)
    parent = await task_service.create_task(
        db, title="编排父卡", task_type="orchestration", creator_id=creator
    )
    steps = [
        orch.PlanStep(no=0, title="取数", skill="data_query", instruction="查", depends_on=[]),
        orch.PlanStep(no=1, title="做报", skill="deliver", instruction="做", depends_on=[0]),
        orch.PlanStep(no=2, title="通知", skill="notify", instruction="发", depends_on=[1]),
    ]
    cards = await orch.build_steps(db, parent.id, steps, creator_id=creator)
    assert len(cards) == 3
    by_no = {c.step_no: c for c in cards}
    # 步骤1 依赖步骤0 的卡 id
    assert by_no[1].depends_on == [str(by_no[0].id)]
    assert by_no[2].depends_on == [str(by_no[1].id)]
    assert by_no[0].depends_on == []
    # 红线标记落 payload
    assert by_no[0].payload["red_line"] is False  # data_query 非红线
    assert by_no[2].payload["red_line"] is True  # notify 红线
    # 都挂在父卡下
    assert all(c.parent_id == parent.id for c in cards)


async def test_build_steps_multi_dependency(db: AsyncSession) -> None:
    """一步依赖多步（DAG 汇聚）。"""
    creator = await _creator(db)
    parent = await task_service.create_task(
        db, title="父", task_type="orchestration", creator_id=creator
    )
    steps = [
        orch.PlanStep(no=0, title="A", skill="data_query", instruction="a", depends_on=[]),
        orch.PlanStep(no=1, title="B", skill="data_query", instruction="b", depends_on=[]),
        orch.PlanStep(no=2, title="汇总", skill="deliver", instruction="c", depends_on=[0, 1]),
    ]
    cards = await orch.build_steps(db, parent.id, steps, creator_id=creator)
    by_no = {c.step_no: c for c in cards}
    assert set(by_no[2].depends_on) == {str(by_no[0].id), str(by_no[1].id)}
