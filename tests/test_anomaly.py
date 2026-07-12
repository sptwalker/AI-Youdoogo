"""指标异常检测单测（纯规则）+ 告警智能体路径（假模型 + 内存 SQLite）。"""

from collections.abc import AsyncGenerator

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.agents import base, ops
from app.core.exceptions import AppError
from app.models import Base
from app.models.agent import AgentRole
from app.services.anomaly import detect_anomalies


def _row(product: str, dau: int, new_users: int | None = None, ret: float | None = None) -> dict:
    return {"product": product, "dau": dau, "new_users": new_users, "retention_d1": ret}


def test_dau_drop_flagged() -> None:
    today = [_row("A", 700)]
    prev = [_row("A", 1000)]
    alerts = detect_anomalies(today, prev)  # 降30% ≥ 20%
    assert len(alerts) == 1 and alerts[0].metric == "dau"


def test_dau_big_drop_is_critical() -> None:
    alerts = detect_anomalies([_row("A", 400)], [_row("A", 1000)])  # 降60% ≥ 40%
    assert alerts[0].severity == "critical"


def test_retention_floor_flagged() -> None:
    alerts = detect_anomalies([_row("A", 1000, ret=25.0)], [_row("A", 1000, ret=25.0)])
    assert any(a.metric == "retention_d1" for a in alerts)


def test_no_anomaly_when_stable() -> None:
    assert detect_anomalies([_row("A", 1000, 100, 45.0)], [_row("A", 1000, 100, 45.0)]) == []


def test_no_baseline_no_dau_alert() -> None:
    """前一日无该产品 → 不判环比降幅（避免误报新品首日）。"""
    alerts = detect_anomalies([_row("A", 1)], [])
    assert all(a.metric != "dau" for a in alerts)


class _FakeLLM:
    async def ainvoke(self, messages: list, **kwargs: object) -> AIMessage:
        return AIMessage(content="【运营告警】产品A 日活骤降，建议排查。")


@pytest.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        session.add(
            AgentRole(
                name=ops.OPS_DIRECTOR_NAME,
                prompt_template="你是运营AI总监。",
                model_role="daily",
            )
        )
        await session.commit()
        yield session
    await engine.dispose()


async def test_generate_anomaly_alert(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(base, "get_llm_for_role", lambda *a, **k: _FakeLLM())
    alerts = detect_anomalies([_row("A", 400)], [_row("A", 1000)])
    record = await ops.generate_anomaly_alert(db, stat_date="2026-07-11", alerts=alerts)
    assert record.status == "success" and record.task_type == "anomaly_alert"
    assert record.output_content and "告警" in record.output_content


async def test_empty_alerts_rejected(db: AsyncSession) -> None:
    with pytest.raises(AppError, match="无异常"):
        await ops.generate_anomaly_alert(db, stat_date="2026-07-11", alerts=[])
