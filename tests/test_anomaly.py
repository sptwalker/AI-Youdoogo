"""指标异常检测单测（纯规则）+ 告警智能体路径（假模型 + 内存 SQLite）。"""

from collections.abc import AsyncGenerator

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.contexts.business.operational_analytics.agent_contracts import MetricAlert
from app.contexts.business.operational_analytics.entrypoints.agent_operations import (
    OPS_DIRECTOR_CODE,
    create_anomaly_alert,
    detect_anomalies,
)
from app.contexts.foundations.model_gateway import public as _mg_public
from app.contexts.shared_kernel import ApplicationError
from app.models import Base
from app.models.agent import AgentRole


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


def test_threshold_overrides_are_preserved() -> None:
    alerts = detect_anomalies(
        [_row("A", 700, 70, 25.0)],
        [_row("A", 1000, 100, 45.0)],
        dau_drop_pct=0.4,
        new_drop_pct=0.4,
        retention_floor=20.0,
    )

    assert alerts == []


def test_alert_result_type_and_order_are_preserved() -> None:
    alerts = detect_anomalies(
        [_row("A", 400, 20, 25.0)],
        [_row("A", 1000, 100, 45.0)],
    )

    assert type(alerts) is list
    assert alerts == [
        MetricAlert("A", "dau", "critical", "日活环比下降 60%（1000→400）"),
        MetricAlert("A", "new_users", "warning", "新增环比下降 80%（100→20）"),
        MetricAlert("A", "retention_d1", "warning", "次留 25.0% 低于地板线 30.0%"),
    ]


def test_invalid_numeric_input_preserves_conversion_error() -> None:
    with pytest.raises(ValueError, match="invalid literal for int"):
        detect_anomalies([{"product": "A", "dau": "invalid"}], [])


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
                name="平台运营部总监助理",
                code=OPS_DIRECTOR_CODE,
                prompt_template="你是平台运营部总监助理。",
                model_role="daily",
            )
        )
        await session.commit()
        yield session
    await engine.dispose()


async def test_generate_anomaly_alert(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_mg_public, "get_llm_for_role",
        lambda *a, **k: _FakeLLM(),
    )
    alerts = detect_anomalies([_row("A", 400)], [_row("A", 1000)])
    record = await create_anomaly_alert(
        db,
        stat_date="2026-07-11",
        alerts=alerts,
        operator_id=None,
    )
    assert record.status == "success" and record.task_type == "anomaly_alert"
    assert record.output_content and "告警" in record.output_content


async def test_empty_alerts_rejected(db: AsyncSession) -> None:
    with pytest.raises(ApplicationError, match="无异常"):
        await create_anomaly_alert(
            db,
            stat_date="2026-07-11",
            alerts=[],
            operator_id=None,
        )
