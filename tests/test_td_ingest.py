"""ThinkingData 运营数据接入 单测：配置驱动 SQL/映射 + 幂等 upsert（假 TD，本地）。"""

from collections.abc import AsyncGenerator
from datetime import date
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.contexts.business.operational_analytics.application import mapping
from app.contexts.business.operational_analytics.entrypoints import operations as ops_data
from app.models import Base
from app.models.sys_config import SysConfig

_MAP_CFG = '{"product":"游戏名","dau":"活跃","new_users":"新增"}'


@pytest.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


class _FakeTD:
    """假 TD 客户端：捕获 SQL、返回固定行。"""

    last_sql = ""
    def __init__(self, **kwargs: Any) -> None:
        pass

    async def query_sql(self, sql: str, **kwargs: Any) -> list[dict[str, Any]]:
        _FakeTD.last_sql = sql
        # 用 TD 原生列名（游戏名/活跃/新增），验证字段映射重命名
        return [
            {"游戏名": "产品A", "活跃": 100, "新增": 10},
            {"游戏名": "产品B", "活跃": 200, "新增": 20},
        ]

    async def close(self) -> None:
        pass


def test_resolve_mapping() -> None:
    assert mapping.resolve_mapping(None) == mapping.DEFAULT_MAPPING
    assert mapping.resolve_mapping("坏JSON") == mapping.DEFAULT_MAPPING
    m = mapping.resolve_mapping('{"dau": "活跃"}')
    assert m["dau"] == "活跃" and m["product"] == "product"  # 部分覆盖 + 默认补齐


async def test_td_ingest_maps_and_upserts(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    db.add(SysConfig(key="td_daily_metrics_sql", value="SELECT * WHERE d='${stat_date}'",
                     value_type="text"))
    db.add(SysConfig(key="td_field_mapping",
                     value=_MAP_CFG, value_type="text"))
    await db.commit()
    monkeypatch.setattr("app.integrations.thinkingdata.client.ThinkingDataClient", _FakeTD)

    res = (await ops_data.sync_thinkingdata(db, date(2026, 7, 14))).to_dict()
    assert res["upserted"] == 2 and res["source"] == "thinkingdata"
    assert "2026-07-14" in _FakeTD.last_sql  # ${stat_date} 已替换

    metrics = [
        snapshot.to_dict() for snapshot in await ops_data.list_daily(db, date(2026, 7, 14))
    ]
    assert {m["product"] for m in metrics} == {"产品A", "产品B"}
    a = next(m for m in metrics if m["product"] == "产品A")
    assert a["dau"] == 100 and a["new_users"] == 10  # 字段映射生效


async def test_td_ingest_idempotent(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    db.add(SysConfig(key="td_daily_metrics_sql", value="q ${stat_date}", value_type="text"))
    db.add(SysConfig(key="td_field_mapping",
                     value=_MAP_CFG, value_type="text"))
    await db.commit()
    monkeypatch.setattr("app.integrations.thinkingdata.client.ThinkingDataClient", _FakeTD)

    d = date(2026, 7, 14)
    await ops_data.sync_thinkingdata(db, d)
    await ops_data.sync_thinkingdata(db, d)  # 重拉不产生重复
    assert len(await ops_data.list_daily(db, d)) == 2


async def test_td_ingest_no_sql_config_rejected(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """未配置 SQL → 明确报错，不静默。"""
    monkeypatch.setattr("app.integrations.thinkingdata.client.ThinkingDataClient", _FakeTD)
    from app.contexts.shared_kernel import ApplicationError

    with pytest.raises(ApplicationError, match="td_daily_metrics_sql"):
        await ops_data.sync_thinkingdata(db, date(2026, 7, 14))


# ── 读取测试（只读不落库）─────────────────────────────────
def _seed_td(db: AsyncSession) -> None:
    db.add(SysConfig(key="td_base_url", value="http://td.example", value_type="string"))
    db.add(SysConfig(key="td_api_secret", value="secret", value_type="string", is_secret=True))
    db.add(SysConfig(key="td_daily_metrics_sql", value="q ${stat_date}", value_type="text"))
    db.add(SysConfig(key="td_field_mapping", value=_MAP_CFG, value_type="text"))


async def test_read_ok_returns_sample_no_write(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """成功读取：回行数+映射后样例，且不落库。"""
    _seed_td(db)
    await db.commit()
    # UI 填的密钥经 runtime_config 生效：覆盖层里放一个 td_api_secret
    monkeypatch.setattr("app.core.runtime_config._overlay", {"td_api_secret": "ui-secret"})
    monkeypatch.setattr("app.integrations.thinkingdata.client.ThinkingDataClient", _FakeTD)

    res = (await ops_data.test_connector(db, date(2026, 7, 14))).to_dict()
    assert res["status"] == "ok" and res["row_count"] == 2
    assert res["sample"][0]["product"] == "产品A" and res["sample"][0]["dau"] == 100
    assert "2026-07-14" in _FakeTD.last_sql
    # 只读：ops_daily_metric 无任何写入
    assert await ops_data.list_daily(db, date(2026, 7, 14)) == ()


async def test_read_not_configured_when_missing(db: AsyncSession) -> None:
    """缺地址/密钥/SQL → not_configured，不发请求。"""
    res = (await ops_data.test_connector(db, date(2026, 7, 14))).to_dict()
    assert res["status"] == "not_configured" and res["row_count"] == 0


async def test_read_reports_td_error(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """TD 报错 → fail + 消息（不抛异常，供 UI 显示）。"""
    _seed_td(db)
    await db.commit()
    monkeypatch.setattr("app.core.runtime_config._overlay", {"td_api_secret": "ui-secret"})

    class _BoomTD(_FakeTD):
        async def query_sql(self, sql: str, **kwargs: Any) -> list[dict[str, Any]]:
            from app.integrations.thinkingdata.client import ThinkingDataError

            raise ThinkingDataError("鉴权失败")

    monkeypatch.setattr("app.integrations.thinkingdata.client.ThinkingDataClient", _BoomTD)
    res = (await ops_data.test_connector(db, date(2026, 7, 14))).to_dict()
    assert res["status"] == "fail" and "鉴权失败" in res["msg"]
