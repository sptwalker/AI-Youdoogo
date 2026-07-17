"""平台运营日指标接入：Excel 上传 + ThinkingData 拉取 → 幂等落库 → 取数供智能体。

两个「入水口」都落到 ops_daily_metric（source 区分），下游看板/AI日报/异常零改动消费。
TD 的 地址/SQL/字段映射 为可编辑配置（sys_config）；密钥经 runtime_config（UI 填优先，回退 .env）。
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


async def _resolve_td_config(db: AsyncSession) -> dict[str, Any]:
    """解析 TD 接入生效配置：地址/密钥/SQL/映射（sys_config 覆盖 .env）。

    密钥经 runtime_config.effective（UI 填的 sys_config 优先，回退 .env），
    返回字典不外泄给前端——仅供本模块建客户端与判空用。
    """
    from app.core import runtime_config
    from app.core.config import get_settings
    from app.services import config_service

    settings = get_settings()
    return {
        "base_url": (await config_service.resolve(db, "td_base_url", "")) or settings.td_base_url,
        "api_secret": str(
            runtime_config.effective("td_api_secret", settings.td_api_secret) or ""
        ),
        "sql_tpl": await config_service.resolve(db, "td_daily_metrics_sql", ""),
        "mapping": _resolve_mapping(await config_service.resolve(db, "td_field_mapping", None)),
    }


async def ingest_from_thinkingdata(db: AsyncSession, stat_date: date) -> dict[str, Any]:
    """从 ThinkingData 拉取某日运营指标 → 按字段映射 → 幂等 upsert（source=thinkingdata）。

    地址/SQL/字段映射走 sys_config（可编辑）；密钥经 runtime_config（UI 填优先，回退 .env）。
    """
    from app.integrations.thinkingdata.client import ThinkingDataClient

    cfg = await _resolve_td_config(db)
    mapping = cfg["mapping"]
    if not cfg["sql_tpl"]:
        from app.core.exceptions import AppError

        raise AppError("未配置 td_daily_metrics_sql（系统配置页设置）")

    sql = cfg["sql_tpl"].replace("${stat_date}", stat_date.isoformat())
    client = ThinkingDataClient(base_url=cfg["base_url"], api_secret=cfg["api_secret"])
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


async def test_read_thinkingdata(db: AsyncSession, stat_date: date) -> dict[str, Any]:
    """用生效配置（含 UI 填的密钥/地址）真跑一次日指标查询，验证能否读到数据。**不落库**。

    回：状态 + 读到行数 + 映射后样例（最多 3 行）；配置缺失回 not_configured。
    绝不回显密钥；异常文本已由 TD 客户端确保不含 token。
    """
    from app.integrations.thinkingdata.client import ThinkingDataClient, ThinkingDataError

    cfg = await _resolve_td_config(db)
    missing = [
        name for name, val in (
            ("TD 地址", cfg["base_url"]),
            ("TD 密钥", cfg["api_secret"]),
            ("拉取 SQL", cfg["sql_tpl"]),
        ) if not val
    ]
    if missing:
        return {"status": "not_configured", "row_count": 0, "sample": [],
                "msg": f"未配置：{'、'.join(missing)}（系统配置页填写）"}

    mapping = cfg["mapping"]
    sql = cfg["sql_tpl"].replace("${stat_date}", stat_date.isoformat())
    client = ThinkingDataClient(base_url=cfg["base_url"], api_secret=cfg["api_secret"])
    try:
        rows = await client.query_sql(sql)
    except ThinkingDataError as exc:
        return {"status": "fail", "row_count": 0, "sample": [], "msg": str(exc)[:200]}
    finally:
        await client.close()

    # 映射后取样，顺带验证配置的列名在结果里存在（列缺失 → 值为 None，提示映射对不上）
    sample = [
        {
            "product": r.get(mapping["product"]),
            "dau": r.get(mapping["dau"]),
            "new_users": r.get(mapping["new_users"]),
        }
        for r in rows[:3]
    ]
    msg = f"读到 {len(rows)} 行" if rows else "查询成功但返回 0 行（检查 SQL 与统计日）"
    return {"status": "ok", "row_count": len(rows), "sample": sample, "msg": msg}


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
