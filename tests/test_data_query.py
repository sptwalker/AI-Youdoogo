"""只读取数服务单测:护栏放行/拒绝、结果截断、审计落库(假 TD + sqlite)。"""

import uuid
from collections.abc import AsyncGenerator
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.contexts.foundations.integration.governed_data_query.contracts import (
    GovernedQueryRequest,
)
from app.contexts.foundations.integration.governed_data_query.entrypoints import (
    agent_capability,
)
from app.contexts.foundations.integration.governed_data_query.entrypoints import (
    operations as data_query,
)
from app.models import Base
from app.models.audit_log import AuditLog
from app.models.sys_config import SysConfig


@pytest.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


# ── validate_dataset:确定性清洗校验（P2）───────────────
def test_validate_dataset_flags_dirty_data() -> None:
    """脏数据产出正确标记：空值 / 类型不一致 / 缺列；干净数据无标记。"""
    columns = ["dau", "revenue", "note"]
    rows = [
        {"dau": 42, "revenue": 100, "note": "ok"},
        {"dau": None, "revenue": "N/A", "note": ""},  # dau 空值；revenue 混文本；note 空串
        {"dau": 7, "revenue": 200},  # note 缺键
    ]
    findings = "\n".join(agent_capability.validate_dataset(columns, rows))
    assert "dau" in findings and "空值" in findings
    assert "revenue" in findings and "类型不一致" in findings
    assert "note" in findings  # 空串 + 缺键都计入空值
    # 干净数据无任何标记
    assert agent_capability.validate_dataset(["c"], [{"c": 1}, {"c": 2}]) == []
    # 声明列但结果完全无该键 → 缺列
    assert any("缺列" in f for f in agent_capability.validate_dataset(["ghost"], [{"c": 1}]))
    # int/float 同属数值，不误报类型不一致
    assert agent_capability.validate_dataset(["x"], [{"x": 1}, {"x": 1.5}]) == []


class _FakeTD:
    """假 TD:记录收到的 SQL，返回 N 行。"""

    last_sql = ""
    n_rows = 3

    def __init__(self, **kwargs: Any) -> None:
        pass

    async def query_sql(self, sql: str, **kwargs: Any) -> list[dict[str, Any]]:
        _FakeTD.last_sql = sql
        return [{"ev": f"e{i}", "cnt": i} for i in range(_FakeTD.n_rows)]

    async def close(self) -> None:
        pass


def _seed(db: AsyncSession) -> None:
    db.add(SysConfig(key="td_base_url", value="http://td", value_type="string"))
    db.add(SysConfig(
        key="td_event_views",
        value='[{"view":"v_event_4","product":"盒子"}]', value_type="text",
    ))


async def _audits(db: AsyncSession) -> list[AuditLog]:
    return list((await db.execute(
        select(AuditLog).where(AuditLog.action == "data.query")
    )).scalars())


async def _query(
    db: AsyncSession,
    sql: str,
    *,
    actor_id: uuid.UUID | None,
    actor_role: str | None,
    max_rows: int = 1000,
) -> dict[str, object]:
    result = await data_query.run_query(
        db,
        GovernedQueryRequest(
            sql=sql,
            actor_id=actor_id,
            actor_role=actor_role,
        ),
        max_rows=max_rows,
    )
    return result.to_dict()


async def test_query_ok_executes_and_audits(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """放行:执行、返回行、补 LIMIT、落一条 ok 审计。"""
    _seed(db)
    await db.commit()
    monkeypatch.setattr("app.core.runtime_config._overlay", {"td_api_secret": "s"})
    monkeypatch.setattr("app.integrations.thinkingdata.client.ThinkingDataClient", _FakeTD)

    res = await _query(
        db,
        "select ev, cnt from v_event_4",
        actor_id=uuid.uuid4(),
        actor_role="admin",
    )
    assert res["status"] == "ok" and res["row_count"] == 3
    assert res["columns"] == ["ev", "cnt"] and res["truncated"] is False
    assert "LIMIT" in _FakeTD.last_sql.upper()  # 护栏补了 LIMIT
    audits = await _audits(db)
    assert len(audits) == 1 and audits[0].result == "ok"


async def test_query_rejected_never_hits_td(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """越权/写 SQL:护栏拒，不建 client，落 rejected 审计。"""
    _seed(db)
    await db.commit()
    monkeypatch.setattr("app.core.runtime_config._overlay", {"td_api_secret": "s"})
    _FakeTD.last_sql = "SENTINEL"

    def _boom(**kwargs: Any) -> Any:  # 若被实例化即失败
        raise AssertionError("rejected SQL 不应触达 TD 客户端")

    monkeypatch.setattr("app.integrations.thinkingdata.client.ThinkingDataClient", _boom)
    res = await _query(
        db, "DROP TABLE v_event_4", actor_id=None, actor_role=None
    )
    assert res["status"] == "rejected" and "SELECT" in res["reason"]
    assert _FakeTD.last_sql == "SENTINEL"  # 未调用
    audits = await _audits(db)
    assert len(audits) == 1 and audits[0].result == "rejected"


async def test_query_unlisted_view_rejected(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """引用未登记视图 → rejected。"""
    _seed(db)
    await db.commit()
    monkeypatch.setattr("app.core.runtime_config._overlay", {"td_api_secret": "s"})
    res = await _query(
        db, "select * from v_event_999", actor_id=None, actor_role=None
    )
    assert res["status"] == "rejected"


async def test_query_truncates_rows(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """超行上限 → 截断 + truncated=True。"""
    _seed(db)
    await db.commit()
    monkeypatch.setattr("app.core.runtime_config._overlay", {"td_api_secret": "s"})
    monkeypatch.setattr(_FakeTD, "n_rows", 5)
    monkeypatch.setattr("app.integrations.thinkingdata.client.ThinkingDataClient", _FakeTD)
    res = await _query(
        db, "select ev from v_event_4", actor_id=None, actor_role=None, max_rows=2
    )
    assert res["row_count"] == 2 and res["truncated"] is True
    monkeypatch.setattr(_FakeTD, "n_rows", 3)  # 复原


async def test_query_not_configured(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """缺密钥 → fail(护栏先过，配置后判空)。"""
    _seed(db)
    await db.commit()
    monkeypatch.setattr("app.core.runtime_config._overlay", {})  # 无密钥
    res = await _query(
        db, "select ev from v_event_4", actor_id=None, actor_role=None
    )
    assert res["status"] == "fail"
