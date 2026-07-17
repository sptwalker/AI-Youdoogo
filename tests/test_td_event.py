"""TD 运营事件命名 单测：事件枚举合并别名 + 别名 upsert/清除（假 TD，本地）。"""

from collections.abc import AsyncGenerator
from datetime import date
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import Base
from app.models.sys_config import SysConfig
from app.models.td_event_alias import TdEventAlias
from app.services import td_event_service


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
    """假 TD：按 SQL 里的视图名返回不同事件行。"""

    def __init__(self, **kwargs: Any) -> None:
        pass

    async def query_sql(self, sql: str, **kwargs: Any) -> list[dict[str, Any]]:
        if "v_event_4" in sql:
            return [{"ev": "new_device", "cnt": 44}, {"ev": "enter_game", "cnt": 3629}]
        if "v_event_5" in sql:
            return [{"ev": "end_game", "cnt": 5290}]
        raise RuntimeError("boom")  # v_event_6 模拟单表失败

    async def close(self) -> None:
        pass


def _seed_cfg(db: AsyncSession) -> None:
    db.add(SysConfig(key="td_base_url", value="http://td", value_type="string"))
    db.add(SysConfig(
        key="td_event_views",
        value='[{"view":"v_event_4","product":"盒子"},{"view":"v_event_5","product":"游戏"},'
              '{"view":"v_event_6","product":"APP"}]',
        value_type="text",
    ))


async def test_list_events_merges_alias_and_isolates_failure(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """列事件：合并已存别名；单表失败转 error 不阻断其余。"""
    _seed_cfg(db)
    db.add(TdEventAlias(view="v_event_4", event_code="new_device", display_name="设备激活"))
    await db.commit()
    monkeypatch.setattr("app.core.runtime_config._overlay", {"td_api_secret": "s"})
    monkeypatch.setattr("app.integrations.thinkingdata.client.ThinkingDataClient", _FakeTD)

    groups = await td_event_service.list_events(db, date(2026, 7, 15))
    assert [g["product"] for g in groups] == ["盒子", "游戏", "APP"]
    box = groups[0]
    nd = next(e for e in box["events"] if e["event_code"] == "new_device")
    assert nd["display_name"] == "设备激活" and nd["count"] == 44  # 别名合并 + 次数
    eg = next(e for e in box["events"] if e["event_code"] == "enter_game")
    assert eg["display_name"] == ""  # 未命名 → 空
    assert groups[2]["error"] and groups[2]["events"] == []  # v_event_6 失败隔离


async def test_list_events_not_configured(db: AsyncSession) -> None:
    """缺地址/密钥 → 每组 error，不发请求。"""
    _seed_cfg(db)
    await db.commit()  # 无 td_api_secret 覆盖 → 密钥空
    groups = await td_event_service.list_events(db, date(2026, 7, 15))
    assert all(g["error"] for g in groups) and all(g["events"] == [] for g in groups)


async def test_save_aliases_upsert_and_clear(db: AsyncSession) -> None:
    """保存：新增 upsert；再存改名;空串清除（软删）。"""
    n1 = await td_event_service.save_aliases(
        db, [{"view": "v_event_4", "event_code": "new_device", "display_name": "设备激活"}]
    )
    assert n1 == 1
    # 改名（同键 upsert，不新增行）
    await td_event_service.save_aliases(
        db, [{"view": "v_event_4", "event_code": "new_device", "display_name": "激活设备"}]
    )
    alive = (await db.execute(
        select(TdEventAlias).where(TdEventAlias.is_delete.is_(False))
    )).scalars().all()
    assert len(alive) == 1 and alive[0].display_name == "激活设备"
    # 空串清除
    await td_event_service.save_aliases(
        db, [{"view": "v_event_4", "event_code": "new_device", "display_name": ""}]
    )
    alive2 = (await db.execute(
        select(TdEventAlias).where(TdEventAlias.is_delete.is_(False))
    )).scalars().all()
    assert alive2 == []


async def test_save_aliases_skips_invalid(db: AsyncSession) -> None:
    """缺 view/event_code 的项跳过，不报错。"""
    n = await td_event_service.save_aliases(
        db, [{"view": "", "event_code": "x", "display_name": "a"},
             {"view": "v", "event_code": "", "display_name": "b"}]
    )
    assert n == 0
