"""评估驱动单测（H3.1，docs/16）:judge 解析纯函数 + run_eval/shadow_compare（打桩 LLM）。"""

import uuid
from collections.abc import AsyncGenerator
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.exceptions import AppError
from app.models import Base
from app.models.agent import AgentRole, AgentTaskRecord
from app.models.eval_case import EvalCase
from app.services import eval_service


@pytest.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


async def _role(db: AsyncSession, prompt: str = "你是助理。") -> AgentRole:
    r = AgentRole(id=uuid.uuid4(), name="评估角色", prompt_template=prompt, model_role="daily")
    db.add(r)
    await db.commit()
    await db.refresh(r)
    return r


# ── judge_score 纯函数 ──────────────────────────────────
def test_judge_score_first_line() -> None:
    assert eval_service.judge_score("4\n理由：切题") == 4
    assert eval_service.judge_score("5") == 5


def test_judge_score_fallback_scan() -> None:
    """首行无数字 → 全文兜底找。"""
    assert eval_service.judge_score("评分如下\n给 2 分") == 2


def test_judge_score_default_three() -> None:
    """完全解析不出 → 兜底 3（中性）。"""
    assert eval_service.judge_score("无法评估") == 3
    assert eval_service.judge_score("") == 3


def test_judge_score_clamps_to_1_5() -> None:
    """只认 1~5（9 不是合法分，跳过找不到则兜底 3）。"""
    assert eval_service.judge_score("9\n超纲") == 3


# ── run_eval / shadow_compare（打桩）────────────────────
def _stub(monkeypatch: pytest.MonkeyPatch, prompt_to_score: dict[str, int]) -> None:
    """打桩 run_agent（回显当前提示词）+ _judge（按提示词给分）。"""
    async def _fake_run(db: Any, role: Any, **kw: Any) -> Any:
        # 产出里带上当前提示词，供 _judge 辨别
        rec = AgentTaskRecord(
            id=uuid.uuid4(), agent_role_id=role.id, task_type="eval_run",
            output_content=f"PROMPT::{role.prompt_template}", status="success",
        )
        return rec

    async def _fake_judge(db: Any, rubric: str, output: str, user_id: Any) -> int:
        for p, sc in prompt_to_score.items():
            if p in output:
                return sc
        return 3

    monkeypatch.setattr("app.agents.base.run_agent", _fake_run)
    monkeypatch.setattr(eval_service, "_judge", _fake_judge)


async def test_run_eval_aggregates(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    role = await _role(db, "当前提示词")
    db.add_all([
        EvalCase(name="c1", role_id=role.id, input_text="x", rubric="r"),
        EvalCase(name="c2", role_id=None, input_text="y", rubric="r"),  # 通用用例也纳入
    ])
    await db.commit()
    _stub(monkeypatch, {"当前提示词": 4})
    res = await eval_service.run_eval(db, role.id)
    assert res["count"] == 2 and res["avg"] == 4.0


async def test_run_eval_no_cases_raises(db: AsyncSession) -> None:
    role = await _role(db)
    with pytest.raises(AppError, match="评估用例"):
        await eval_service.run_eval(db, role.id)


async def test_shadow_compare_detects_improvement(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """候选提示词得分更高 → improved=True + delta>0。"""
    role = await _role(db, "旧提示词")
    db.add(EvalCase(name="c", role_id=role.id, input_text="x", rubric="r"))
    await db.commit()
    _stub(monkeypatch, {"旧提示词": 3, "新提示词": 5})
    res = await eval_service.shadow_compare(db, role.id, "新提示词")
    assert res["baseline_avg"] == 3.0 and res["candidate_avg"] == 5.0
    assert res["delta"] == 2.0 and res["improved"] is True


async def test_shadow_compare_restores_prompt(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """影子评估跑完后角色提示词必须还原（绝不把候选落到角色）。"""
    role = await _role(db, "原始提示词")
    db.add(EvalCase(name="c", role_id=role.id, input_text="x", rubric="r"))
    await db.commit()
    _stub(monkeypatch, {"原始提示词": 3, "候选提示词": 4})
    await eval_service.shadow_compare(db, role.id, "候选提示词")
    await db.refresh(role)
    assert role.prompt_template == "原始提示词"  # 还原，未被污染


# ── CRUD ────────────────────────────────────────────────
async def test_create_and_list_case(db: AsyncSession) -> None:
    r = await eval_service.create_case(
        db, {"name": "用例1", "input_text": "查数据", "rubric": "准确"}
    )
    assert r["name"] == "用例1"
    cases = await eval_service.list_cases(db)
    assert len(cases) == 1 and cases[0]["rubric"] == "准确"


async def test_create_case_requires_input(db: AsyncSession) -> None:
    with pytest.raises(AppError, match="必填"):
        await eval_service.create_case(db, {"name": "x", "input_text": "  "})


async def test_delete_case(db: AsyncSession) -> None:
    r = await eval_service.create_case(db, {"name": "c", "input_text": "x"})
    await eval_service.delete_case(db, uuid.UUID(r["id"]))
    assert await eval_service.list_cases(db) == []
