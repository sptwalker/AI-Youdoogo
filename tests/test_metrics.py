"""可观测单测（H2.4，docs/16 P1）:Prometheus 指标渲染 + readiness 探针。"""

import uuid
from collections.abc import AsyncGenerator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.bootstrap import observability as legacy_metrics_service
from app.bootstrap.observability import readiness, render_metrics
from app.core import shared_state
from app.models import Base
from app.models.agent import AgentRole, AgentTaskRecord
from app.models.ai_provider import AiProvider
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


# ── 指标渲染 ────────────────────────────────────────────
async def test_render_metrics_prometheus_format(db: AsyncSession) -> None:
    db.add_all([
        LlmCallLog(role="daily", model="m", total_tokens=100, status="success"),
        LlmCallLog(role="daily", model="m", total_tokens=50, status="failed"),
    ])
    await db.commit()
    out = await render_metrics(db)
    assert "# TYPE youdoo_llm_calls_total counter" in out
    assert 'youdoo_llm_calls_total{status="success"} 1' in out
    assert 'youdoo_llm_calls_total{status="failed"} 1' in out
    assert "youdoo_llm_tokens_total 150" in out
    assert "youdoo_up 1" in out


async def test_render_metrics_empty_db(db: AsyncSession) -> None:
    """空库也能渲染（至少 youdoo_up）。"""
    out = await render_metrics(db)
    assert "youdoo_up 1" in out


async def test_render_metrics_counts_agent_tasks(db: AsyncSession) -> None:
    role = AgentRole(id=uuid.uuid4(), name="a", prompt_template="x")
    db.add(role)
    await db.commit()
    db.add_all([
        AgentTaskRecord(agent_role_id=role.id, task_type="t", status="success"),
        AgentTaskRecord(agent_role_id=role.id, task_type="t", status="success"),
    ])
    await db.commit()
    out = await render_metrics(db)
    assert 'youdoo_agent_tasks_total{status="success"} 2' in out


# ── readiness 探针 ──────────────────────────────────────
async def test_readiness_ready_with_active_card(db: AsyncSession) -> None:
    db.add(AiProvider(
        id=uuid.uuid4(), name="c", tier="daily", base_url="https://x.com",
        api_key="sk", model="m", is_active=True,
    ))
    await db.commit()
    ready, detail = await readiness(db)
    assert ready is True and detail["ai_cards_active"] == 1


async def test_readiness_not_ready_no_card(db: AsyncSession) -> None:
    """无 active 卡片 → 未就绪（AI 不可用）。"""
    ready, detail = await readiness(db)
    assert ready is False and detail["ai_cards_active"] == 0
    assert "reason" in detail


def test_legacy_service_exports_bootstrap_observability_functions() -> None:
    assert legacy_metrics_service.render_metrics is render_metrics
    assert legacy_metrics_service.readiness is readiness
