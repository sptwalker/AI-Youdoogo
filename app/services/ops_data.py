"""平台运营日指标接入：Excel 上传 + ThinkingData 拉取 → 幂等落库 → 取数供智能体。

两个「入水口」都落到 ops_daily_metric（source 区分），下游看板/AI日报/异常零改动消费。
TD 的 地址/SQL/字段映射 均为可编辑配置（sys_config），密钥仍走 .env（密钥红线）。
"""

from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ops_data import OpsDailyMetric
from app.services.excel_ingest import parse_workbook

logger = logging.getLogger(__name__)

_FIELDS = ("dau", "new_users", "retention_d1")
# 配置缺失时的内置兜底（与迁移 017 种子一致）
_DEFAULT_MAPPING = {"product": "product", "dau": "dau", "new_users": "new_users"}


async def _upsert_metric(
    db: AsyncSession, *, stat_date: date, product: str, source: str, **fields: Any
) -> None:
    """按 (stat_date, product) 幂等 upsert 一行指标。调用方负责 commit。"""
    existing = (
        await db.execute(
            select(OpsDailyMetric).where(
                OpsDailyMetric.stat_date == stat_date,
                OpsDailyMetric.product == product,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        db.add(
            OpsDailyMetric(
                stat_date=stat_date, product=product, source=source,
                **{k: fields.get(k) for k in _FIELDS},
            )
        )
    else:
        for k in _FIELDS:
            if k in fields:
                setattr(existing, k, fields.get(k))
        existing.source = source


async def ingest_ops_daily_excel(db: AsyncSession, content: bytes) -> dict[str, Any]:
    """解析 ops_daily 模板 Excel 并按 (stat_date, product) 幂等 upsert。

    Raises:
        ExcelParseError: 文件损坏 / 无法匹配模板（由 excel_ingest 抛，API 层转 AppError）。
    """
    result = parse_workbook(content)
    for row in result.rows:
        await _upsert_metric(
            db, stat_date=row["stat_date"], product=row["product"], source="excel",
            **{k: row.get(k) for k in _FIELDS},
        )
    await db.commit()
    return {
        "template": result.template,
        "upserted": len(result.rows),
        "duplicates": result.duplicate_count,
        "errors": [
            {"row_no": e.row_no, "field": e.field, "message": e.message} for e in result.errors
        ],
    }


async def ingest_from_thinkingdata(db: AsyncSession, stat_date: date) -> dict[str, Any]:
    """从 ThinkingData 拉取某日运营指标 → 按字段映射 → 幂等 upsert（source=thinkingdata）。

    地址/SQL/字段映射走 sys_config（可编辑）；密钥走 .env。
    """
    from app.core.config import get_settings
    from app.integrations.thinkingdata.client import ThinkingDataClient
    from app.services import config_service

    settings = get_settings()
    base_url = (await config_service.resolve(db, "td_base_url", "")) or settings.td_base_url
    sql_tpl = await config_service.resolve(db, "td_daily_metrics_sql", "")
    mapping = _resolve_mapping(await config_service.resolve(db, "td_field_mapping", None))
    if not sql_tpl:
        from app.core.exceptions import AppError

        raise AppError("未配置 td_daily_metrics_sql（系统配置页设置）")

    sql = sql_tpl.replace("${stat_date}", stat_date.isoformat())
    client = ThinkingDataClient(base_url=base_url, api_secret=settings.td_api_secret)
    try:
        rows = await client.query_sql(sql)
    finally:
        await client.close()

    n = 0
    for r in rows:
        product = str(r.get(mapping["product"]) or "").strip()
        if not product:
            continue
        await _upsert_metric(
            db, stat_date=stat_date, product=product, source="thinkingdata",
            dau=r.get(mapping["dau"]), new_users=r.get(mapping["new_users"]),
        )
        n += 1
    await db.commit()
    logger.info("TD 运营指标入库：%s，%s 行", stat_date.isoformat(), n)
    return {"date": stat_date.isoformat(), "upserted": n, "source": "thinkingdata"}


def _resolve_mapping(raw: Any) -> dict[str, str]:
    """字段映射配置容错解析：JSON 串/字典/缺失都归一为映射字典，坏值回退默认。"""
    if isinstance(raw, dict):
        merged = {**_DEFAULT_MAPPING, **raw}
        return {k: str(merged[k]) for k in _DEFAULT_MAPPING}
    if isinstance(raw, str) and raw.strip():
        try:
            return _resolve_mapping(json.loads(raw))
        except json.JSONDecodeError:
            logger.warning("td_field_mapping 非法 JSON，回退默认映射")
    return dict(_DEFAULT_MAPPING)


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
