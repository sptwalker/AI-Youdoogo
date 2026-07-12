"""运营数据接入单测：Excel 解析 → 幂等 upsert → 取数（内存 SQLite）。"""

from collections.abc import AsyncGenerator
from datetime import date
from io import BytesIO

import pytest
from openpyxl import Workbook
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import Base
from app.models.ops_data import OpsDailyMetric
from app.services.ops_data import get_ops_metrics, ingest_ops_daily_excel

HEADERS = ["日期", "产品", "日活", "新增", "次留"]


def _xlsx(rows: list[list]) -> bytes:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.append(HEADERS)
    for r in rows:
        ws.append(r)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def test_ingest_and_query(db: AsyncSession) -> None:
    content = _xlsx(
        [
            ["2026-07-11", "产品A", 1234, 56, 42.5],
            ["2026-07-11", "产品B", 2000, None, None],
        ]
    )
    summary = await ingest_ops_daily_excel(db, content)
    assert summary["upserted"] == 2 and summary["errors"] == []

    metrics = await get_ops_metrics(db, date(2026, 7, 11))
    assert [m["product"] for m in metrics] == ["产品A", "产品B"]
    assert metrics[0]["dau"] == 1234 and metrics[0]["retention_d1"] == 42.5


async def test_reupload_is_idempotent_upsert(db: AsyncSession) -> None:
    await ingest_ops_daily_excel(db, _xlsx([["2026-07-11", "产品A", 100, None, None]]))
    await ingest_ops_daily_excel(db, _xlsx([["2026-07-11", "产品A", 999, 10, None]]))  # 覆盖
    count = (await db.execute(select(func.count()).select_from(OpsDailyMetric))).scalar_one()
    assert count == 1  # 同 (日期,产品) 未新增，就地更新
    metrics = await get_ops_metrics(db, date(2026, 7, 11))
    assert metrics[0]["dau"] == 999 and metrics[0]["new_users"] == 10
