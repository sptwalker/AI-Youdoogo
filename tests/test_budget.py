"""LLM 预算硬闸 + 成本归因单测（H2.2，docs/16 P1）。

budget_exceeded 依赖 config 开关 + Redis 原子计数(shared_state);用 monkeypatch 控 settings。
"""

import uuid
from collections.abc import AsyncGenerator

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core import shared_state
from app.llm import usage
from app.models import Base
from app.models.llm_log import LlmCallLog


@pytest.fixture(autouse=True)
def _reset() -> None:
    shared_state.reset()
    yield
    shared_state.reset()


@pytest.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


class _S:
    """假 settings。"""
    def __init__(self, budget: int, hard: bool) -> None:
        self.llm_daily_token_budget = budget
        self.llm_budget_hard_limit = hard


# ── 硬闸 budget_exceeded ────────────────────────────────
def test_budget_not_exceeded_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """预算=0（不启用）→ 恒 False。"""
    monkeypatch.setattr(usage, "get_settings", lambda: _S(0, True))
    assert usage.budget_exceeded() is False


def test_budget_not_exceeded_when_soft(monkeypatch: pytest.MonkeyPatch) -> None:
    """硬闸关（软告警模式）→ 恒 False，即使已超。"""
    monkeypatch.setattr(usage, "get_settings", lambda: _S(100, False))
    from datetime import UTC, datetime
    day = datetime.now(UTC).strftime("%Y-%m-%d")
    shared_state.budget_add(day, 500)  # 远超
    assert usage.budget_exceeded() is False  # 软模式不拦


def test_budget_exceeded_when_hard_and_over(monkeypatch: pytest.MonkeyPatch) -> None:
    """硬闸开 + 已超预算 → True（拒绝新调用）。"""
    monkeypatch.setattr(usage, "get_settings", lambda: _S(100, True))
    from datetime import UTC, datetime
    day = datetime.now(UTC).strftime("%Y-%m-%d")
    shared_state.budget_add(day, 150)
    assert usage.budget_exceeded() is True


def test_budget_not_exceeded_when_hard_under(monkeypatch: pytest.MonkeyPatch) -> None:
    """硬闸开 + 未超 → False。"""
    monkeypatch.setattr(usage, "get_settings", lambda: _S(100, True))
    from datetime import UTC, datetime
    day = datetime.now(UTC).strftime("%Y-%m-%d")
    shared_state.budget_add(day, 50)
    assert usage.budget_exceeded() is False


# ── 成本归因 department_id ──────────────────────────────
async def test_record_usage_persists_department(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """record_usage 落 department_id（部门级成本归因）。"""
    monkeypatch.setattr(usage, "get_settings", lambda: _S(0, False))  # 关预算免告警
    dept = uuid.uuid4()
    await usage.record_usage(
        db, role="daily", model="m1", total_tokens=100,
        user_id=uuid.uuid4(), department_id=dept,
    )
    row = (await db.execute(select(LlmCallLog))).scalar_one()
    assert row.department_id == dept and row.total_tokens == 100
