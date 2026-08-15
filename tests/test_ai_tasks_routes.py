"""A6 AI 任务中心入口（/ai-tasks/plan 预览 + /ai-tasks/execute 执行）路由级回归。

红线（docs/27 §十一）：对外/业务/资金/人事步骤必须停 waiting_human，本入口不得绕过。
预览只出计划不落库、不执行；执行用真人已确认的步骤重建 WorkflowPlan（复校 DAG，非法 → 400）。
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api import deps
from app.contexts.foundations.execution.work_planning import public as work_planning
from app.main import app
from app.models import Base
from app.models.system import SysUser
from app.models.workflow import STEP_WAITING_HUMAN, WorkflowRun
from app.platform.database import get_db
from tests import workflow_testkit as wf


@pytest.fixture
async def ai_client(
    tmp_path: Path,
) -> AsyncGenerator[tuple[AsyncClient, dict[str, Any]], None]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ai_tasks.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    user = SysUser(username="ai-owner", password_hash="x", role_code="admin")
    async with factory() as session:
        session.add(user)
        await session.commit()

    async def _override_db() -> AsyncGenerator[AsyncSession, None]:
        async with factory() as session:
            yield session

    async def _current_user() -> SysUser:
        return user

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[deps.get_current_user] = _current_user
    state: dict[str, Any] = {"factory": factory, "user": user}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, state
    app.dependency_overrides.clear()
    await engine.dispose()


def _plan(user_id: uuid.UUID) -> work_planning.WorkflowPlan:
    return work_planning.WorkflowPlan(
        work_planning.WorkIntent(request="做月度经营报告", creator_id=user_id, title="月报"),
        (
            work_planning.WorkflowPlanStep(0, "取数", "data_query", "查销售数据"),
            work_planning.WorkflowPlanStep(1, "汇总", "deliver", "汇总成稿", depends_on=(0,)),
        ),
    )


async def test_plan_preview_returns_steps_without_executing(
    ai_client: tuple[AsyncClient, dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """/plan 只跑规划器出预览：返回 DAG 步骤，且不落任何 WorkflowRun（未执行）。"""
    client, state = ai_client

    async def _fake(_request: work_planning.PlanWorkRequest) -> work_planning.PlanWorkResult:
        return work_planning.PlanWorkResult(_plan(state["user"].id))

    monkeypatch.setattr(work_planning, "plan_work", _fake)
    response = await client.post("/api/v1/ai-tasks/plan", json={"request": "帮我做月度经营报告"})
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["reason"] is None
    assert [step["capability_key"] for step in data["plan"]["steps"]] == ["data_query", "deliver"]
    assert data["plan"]["steps"][1]["depends_on"] == [0]

    # 红线/懒惰双证：预览不执行 → 一条 WorkflowRun 都没有。
    async with state["factory"]() as session:
        runs = (await session.execute(select(WorkflowRun))).scalars().all()
    assert runs == []


async def test_plan_preview_single_action_returns_null_plan(
    ai_client: tuple[AsyncClient, dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """非多步（单动作/步数不足/解析失败）→ plan=None + reason，前端提示走普通任务卡。"""
    client, _ = ai_client

    async def _fake(_request: work_planning.PlanWorkRequest) -> work_planning.PlanWorkResult:
        return work_planning.PlanWorkResult(None, "single_action")

    monkeypatch.setattr(work_planning, "plan_work", _fake)
    response = await client.post(
        "/api/v1/ai-tasks/plan", json={"request": "请给张三发一条通知消息"}
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["plan"] is None
    assert data["reason"] == "single_action"


async def test_execute_rejects_invalid_dag(
    ai_client: tuple[AsyncClient, dict[str, Any]],
) -> None:
    """执行时在信任边界复校 DAG：依赖未知步 → WorkflowPlan 抛错 → 400，不启动任何 run。"""
    client, state = ai_client
    response = await client.post(
        "/api/v1/ai-tasks/execute",
        json={
            "request": "两步任务但依赖非法",
            "steps": [
                {"number": 0, "title": "取数", "capability_key": "data_query", "instruction": "查"},
                {
                    "number": 1,
                    "title": "汇总",
                    "capability_key": "deliver",
                    "instruction": "汇总",
                    "depends_on": [5],  # 未知步号 → 非法 DAG
                },
            ],
        },
    )
    assert response.status_code == 400
    async with state["factory"]() as session:
        runs = (await session.execute(select(WorkflowRun))).scalars().all()
    assert runs == []


async def test_execute_redline_step_stops_at_waiting_human(
    ai_client: tuple[AsyncClient, dict[str, Any]],
) -> None:
    """红线闸门：对外步骤（notify）执行后停 waiting_human，等真人验收，不自动完成下游。"""
    client, state = ai_client
    response = await client.post(
        "/api/v1/ai-tasks/execute",
        json={
            "request": "先对外通知再交付",
            "title": "带红线的编排",
            "steps": [
                {
                    "number": 0,
                    "title": "对外通知",
                    "capability_key": "notify",
                    "instruction": "通知客户",
                },
                {
                    "number": 1,
                    "title": "交付",
                    "capability_key": "deliver",
                    "instruction": "交付结果",
                    "depends_on": [0],
                },
            ],
        },
    )
    assert response.status_code == 200
    snapshot = response.json()["data"]
    # 启动即标记红线步：notify 步 red_line=true（runtime 会据此停 waiting_human）。
    notify = next(step for step in snapshot["steps"] if step["skill"] == "notify")
    assert notify["red_line"] is True
    assert snapshot["done"] is False
    parent_id = uuid.UUID(snapshot["parent_id"])

    # 驱动红线步的工作完成 → 应停在 waiting_human（不因完成而自动验收）。
    async with state["factory"]() as session:
        run = (await session.execute(select(WorkflowRun))).scalar_one()
        first, _second = await wf.list_steps(session, run.id)
        claimed = await wf.claim_step(session, first.id, worker_id="w", lease_seconds=60)
        assert claimed is not None
        assert await wf.complete_step(
            session, claimed, worker_id="w", output_data={}, result_content="草稿", succeeded=True
        )
        await session.commit()
        await session.refresh(first)
        assert first.status == STEP_WAITING_HUMAN  # 红线停点：等真人，未 SUCCEEDED

    # 进度快照据此把红线步列入 awaiting_human，整体未完成。
    progress = await client.get(f"/api/v1/tasks/{parent_id}/orchestration")
    assert progress.status_code == 200
    body = progress.json()["data"]
    assert body["awaiting_human"], "红线步必须进入 awaiting_human 等真人验收"
    assert body["done"] is False
