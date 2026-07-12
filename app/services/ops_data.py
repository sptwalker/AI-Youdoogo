"""平台运营日指标接入：Excel 解析（复用 excel_ingest）→ 幂等落库 → 取数供智能体。"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ops_data import OpsDailyMetric
from app.services.excel_ingest import parse_workbook

_FIELDS = ("dau", "new_users", "retention_d1")


async def ingest_ops_daily_excel(db: AsyncSession, content: bytes) -> dict[str, Any]:
    """解析 ops_daily 模板 Excel 并按 (stat_date, product) 幂等 upsert。

    Raises:
        ExcelParseError: 文件损坏 / 无法匹配模板（由 excel_ingest 抛，API 层转 AppError）。
    """
    result = parse_workbook(content)
    upserted = 0
    for row in result.rows:
        existing = (
            await db.execute(
                select(OpsDailyMetric).where(
                    OpsDailyMetric.stat_date == row["stat_date"],
                    OpsDailyMetric.product == row["product"],
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            keys = ("stat_date", "product", *_FIELDS)
            db.add(OpsDailyMetric(source="excel", **{k: row.get(k) for k in keys}))
        else:
            for k in _FIELDS:
                setattr(existing, k, row.get(k))
            existing.source = "excel"
        upserted += 1
    await db.commit()
    return {
        "template": result.template,
        "upserted": upserted,
        "duplicates": result.duplicate_count,
        "errors": [
            {"row_no": e.row_no, "field": e.field, "message": e.message} for e in result.errors
        ],
    }


async def get_ops_metrics(db: AsyncSession, stat_date: date) -> list[dict[str, Any]]:
    """取某日全部产品的运营指标（供运营日报/异常告警取数）。"""
    stmt = (
        select(OpsDailyMetric)
        .where(OpsDailyMetric.stat_date == stat_date, OpsDailyMetric.is_delete.is_(False))
        .order_by(OpsDailyMetric.product)
    )
    rows = (await db.execute(stmt)).scalars()
    return [
        {
            "stat_date": r.stat_date.isoformat(),
            "product": r.product,
            "dau": r.dau,
            "new_users": r.new_users,
            "retention_d1": r.retention_d1,
        }
        for r in rows
    ]
