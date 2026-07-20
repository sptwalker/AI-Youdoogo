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


# ── B.2 调度驱动 ────────────────────────────────────────
from app.services import task_flow  # noqa: E402
from app.services.collab_protocol import ProtocolResult  # noqa: E402


async def _parent_with_steps(
    db: AsyncSession, steps: list[orch.PlanStep]
) -> tuple[uuid.UUID, uuid.UUID, dict[int, Any]]:
    """建父卡 + 步骤卡，返回 (creator, parent_id, no→card)。"""
    creator = await _creator(db)
    parent = await task_service.create_task(
        db, title="编排", task_type="orchestration", creator_id=creator
    )
    cards = await orch.build_steps(db, parent.id, steps, creator_id=creator)
    return creator, parent.id, {c.step_no: c for c in cards}


def _ready_titles(steps: list[Any]) -> set[str]:
    return {s.title for s in orch._ready_steps(steps)}


async def test_ready_steps_gated_by_deps(db: AsyncSession) -> None:
    """只有依赖全 accepted 的步骤才 ready。"""
    _, pid, by_no = await _parent_with_steps(db, [
        orch.PlanStep(no=0, title="A", skill="data_query", instruction="a", depends_on=[]),
        orch.PlanStep(no=1, title="B", skill="deliver", instruction="b", depends_on=[0]),
    ])
    steps = await orch._step_cards(db, pid)
    assert _ready_titles(steps) == {"A"}  # B 依赖未完成
    # 手动把 A accept，B 才 ready
    by_no[0].status = task_flow.ACCEPTED
    await db.commit()
    steps = await orch._step_cards(db, pid)
    assert _ready_titles(steps) == {"B"}


async def test_advance_auto_runs_non_redline_pipes_output(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """全非红线链:两步都自动跑完 + 上游 datasets 喂到下游 step_input + 编排完成。"""
    _, pid, by_no = await _parent_with_steps(db, [
        orch.PlanStep(no=0, title="取数", skill="data_query", instruction="查", depends_on=[]),
        orch.PlanStep(no=1, title="做报", skill="deliver", instruction="做", depends_on=[0]),
    ])
    ran: list[str] = []

    async def _fake_run(_db: Any, step: Any, operator_id: Any) -> ProtocolResult | None:
        ran.append(step.title)
        await orch._to_reported(_db, step, operator_id, "stub", "ok")
        p = ProtocolResult()
        if step.task_type == "data_query":
            p.datasets.append({"sql": "q", "columns": ["dau"], "rows": [{"dau": 42}]})
        return p

    monkeypatch.setattr(orch, "_run_step", _fake_run)
    snap = await orch.advance(db, pid, operator_id=None)
    assert ran == ["取数", "做报"]  # 拓扑序
    assert snap["done"] is True and snap["accepted"] == 2
    # 上游 datasets 已喂到下游 step_input
    await db.refresh(by_no[1])
    assert by_no[1].step_input["datasets"][0]["rows"] == [{"dau": 42}]


async def test_advance_stops_at_redline(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """红线步骤执行到 reported 后停下，不 accept、不解锁下游。"""
    _, pid, by_no = await _parent_with_steps(db, [
        orch.PlanStep(no=0, title="取数", skill="data_query", instruction="查", depends_on=[]),
        orch.PlanStep(no=1, title="通知", skill="notify", instruction="发", depends_on=[0]),
    ])

    async def _fake_run(_db: Any, step: Any, operator_id: Any) -> ProtocolResult | None:
        await orch._to_reported(_db, step, operator_id, "stub", "ok")
        return ProtocolResult()

    monkeypatch.setattr(orch, "_run_step", _fake_run)
    snap = await orch.advance(db, pid, operator_id=None)
    # 取数自动 accept；通知红线停在 reported
    await db.refresh(by_no[0])
    await db.refresh(by_no[1])
    assert by_no[0].status == task_flow.ACCEPTED
    assert by_no[1].status == task_flow.REPORTED
    assert snap["done"] is False
    assert str(by_no[1].id) in snap["awaiting_human"]


async def test_advance_resume_after_human_accept(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """红线步被真人 accept 后再 advance → 从停点继续跑完下游。"""
    _, pid, by_no = await _parent_with_steps(db, [
        orch.PlanStep(no=0, title="审批", skill="notify", instruction="批", depends_on=[]),
        orch.PlanStep(no=1, title="交付", skill="deliver", instruction="交", depends_on=[0]),
    ])

    async def _fake_run(_db: Any, step: Any, operator_id: Any) -> ProtocolResult | None:
        await orch._to_reported(_db, step, operator_id, "stub", "ok")
        return ProtocolResult()

    monkeypatch.setattr(orch, "_run_step", _fake_run)
    snap1 = await orch.advance(db, pid, operator_id=None)
    assert snap1["done"] is False  # 卡在红线审批步
    # 真人验收红线步
    await task_service.transition(
        db, by_no[0].id, task_flow.ACCEPTED, operator_id=None, note="真人验收"
    )
    snap2 = await orch.advance(db, pid, operator_id=None)
    await db.refresh(by_no[1])
    assert by_no[1].status == task_flow.ACCEPTED and snap2["done"] is True


async def test_advance_failed_step_blocks_downstream(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """步骤失败（_run_step 返 None）→ 停在 reported，下游不解锁。"""
    _, pid, by_no = await _parent_with_steps(db, [
        orch.PlanStep(no=0, title="取数", skill="data_query", instruction="查", depends_on=[]),
        orch.PlanStep(no=1, title="做报", skill="deliver", instruction="做", depends_on=[0]),
    ])

    async def _fake_run(_db: Any, step: Any, operator_id: Any) -> ProtocolResult | None:
        await orch._to_reported(_db, step, operator_id, "失败", "err")
        return None  # 失败

    monkeypatch.setattr(orch, "_run_step", _fake_run)
    snap = await orch.advance(db, pid, operator_id=None)
    await db.refresh(by_no[1])
    assert by_no[1].status == task_flow.CREATED  # 下游从未启动
    assert snap["done"] is False


# ── start / resume 入口 ─────────────────────────────────
async def test_start_non_composite_returns_none(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """plan 判定单动作 → start 返 None（走原路），不建卡。"""
    async def _no_plan(_db: Any, req: str) -> Any:
        return None

    monkeypatch.setattr(orch, "plan", _no_plan)
    creator = await _creator(db)
    snap = await orch.start(
        db, "今天天气如何呀", creator_id=creator, assignee_agent_id=None, operator_id=creator
    )
    assert snap is None
    assert await task_service.list_tasks(db) == []  # 未建任何卡


async def test_start_short_message_skips_planning(db: AsyncSession) -> None:
    """短消息（问候）不进规划，直接 None。"""
    creator = await _creator(db)
    assert await orch.start(
        db, "你好", creator_id=creator, assignee_agent_id=None, operator_id=creator
    ) is None


async def test_start_builds_and_advances(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """复合任务 → 建父卡+步骤卡+推进（非红线自动跑，红线停）。"""
    async def _plan(_db: Any, req: str) -> Any:
        return [
            orch.PlanStep(no=0, title="取数", skill="data_query", instruction="查", depends_on=[]),
            orch.PlanStep(no=1, title="通知", skill="notify", instruction="发", depends_on=[0]),
        ]

    async def _fake_run(_db: Any, step: Any, operator_id: Any) -> Any:
        await orch._to_reported(_db, step, operator_id, "stub", "ok")
        return ProtocolResult()

    monkeypatch.setattr(orch, "plan", _plan)
    monkeypatch.setattr(orch, "_run_step", _fake_run)
    creator = await _creator(db)
    snap = await orch.start(
        db, "取昨天数据并通知总监", creator_id=creator,
        assignee_agent_id=None, operator_id=creator,
    )
    assert snap is not None and snap["total"] == 2
    assert snap["done"] is False and len(snap["awaiting_human"]) == 1  # 停在红线通知步


async def test_resume_if_step_non_step_returns_none(db: AsyncSession) -> None:
    """非编排步骤卡（无 step_no）→ resume 返 None。"""
    creator = await _creator(db)
    plain = await task_service.create_task(
        db, title="普通卡", task_type="manual", creator_id=creator
    )
    assert await orch.resume_if_step(db, plain, operator_id=creator) is None


# ── H4.1 崩溃恢复扫描 ───────────────────────────────────
async def test_recover_resets_orphan_and_advances(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """崩溃恢复:executing 父卡下卡在 executing 的孤儿步复位 created，再 advance 跑完。"""
    creator = await _creator(db)
    parent = await task_service.create_task(
        db, title="编排", task_type="orchestration", creator_id=creator
    )
    parent.status = task_flow.EXECUTING  # 模拟崩溃时父卡在执行中
    cards = await orch.build_steps(db, parent.id, [
        orch.PlanStep(no=0, title="取数", skill="data_query", instruction="查", depends_on=[]),
        orch.PlanStep(no=1, title="交付", skill="deliver", instruction="做", depends_on=[0]),
    ], creator_id=creator)
    by_no = {c.step_no: c for c in cards}
    by_no[0].status = task_flow.EXECUTING  # 崩溃时步骤0卡在执行中（孤儿）
    await db.commit()

    ran: list[str] = []

    async def _fake_run(_db: Any, step: Any, operator_id: Any) -> Any:
        ran.append(step.title)
        await orch._to_reported(_db, step, operator_id, "stub", "ok")
        return ProtocolResult()

    monkeypatch.setattr(orch, "_run_step", _fake_run)
    res = await orch.recover_incomplete(db)
    assert res["orchestrations"] == 1 and res["steps_reset"] == 1
    # 孤儿步复位后重跑，全链跑完
    await db.refresh(by_no[0])
    await db.refresh(by_no[1])
    assert by_no[0].status == task_flow.ACCEPTED
    assert by_no[1].status == task_flow.ACCEPTED
    assert "取数" in ran


async def test_recover_ignores_non_executing_parents(db: AsyncSession) -> None:
    """已完成（非 executing）的编排不被恢复扫描碰。"""
    creator = await _creator(db)
    done_parent = await task_service.create_task(
        db, title="已完成编排", task_type="orchestration", creator_id=creator
    )
    done_parent.status = task_flow.ACCEPTED
    await db.commit()
    res = await orch.recover_incomplete(db)
    assert res["orchestrations"] == 0  # accepted 父卡不扫


async def test_recover_no_incomplete_is_noop(db: AsyncSession) -> None:
    """无未完成编排 → 空操作。"""
    res = await orch.recover_incomplete(db)
    assert res == {"orchestrations": 0, "steps_reset": 0}
