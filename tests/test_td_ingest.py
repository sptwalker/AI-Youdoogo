"""ThinkingData 运营数据接入 单测：配置驱动 SQL/映射 + 幂等 upsert（假 TD，本地）。"""

from collections.abc import AsyncGenerator
from datetime import date
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import Base
from app.models.sys_config import SysConfig
from app.services import ops_data

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
    assert ops_data._resolve_mapping(None) == ops_data._DEFAULT_MAPPING
    assert ops_data._resolve_mapping("坏JSON") == ops_data._DEFAULT_MAPPING
    m = ops_data._resolve_mapping('{"dau": "活跃"}')
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

    res = await ops_data.ingest_from_thinkingdata(db, date(2026, 7, 14))
    assert res["upserted"] == 2 and res["source"] == "thinkingdata"
    assert "2026-07-14" in _FakeTD.last_sql  # ${stat_date} 已替换

    metrics = await ops_data.get_ops_metrics(db, date(2026, 7, 14))
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
    await ops_data.ingest_from_thinkingdata(db, d)
    await ops_data.ingest_from_thinkingdata(db, d)  # 重拉不产生重复
    assert len(await ops_data.get_ops_metrics(db, d)) == 2


async def test_td_ingest_no_sql_config_rejected(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """未配置 SQL → 明确报错，不静默。"""
    monkeypatch.setattr("app.integrations.thinkingdata.client.ThinkingDataClient", _FakeTD)
    from app.core.exceptions import AppError

    with pytest.raises(AppError, match="td_daily_metrics_sql"):
        await ops_data.ingest_from_thinkingdata(db, date(2026, 7, 14))
