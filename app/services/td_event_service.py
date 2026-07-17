"""TD 运营事件枚举与命名（数据接口页「运营事件命名」）。

- list_events：从 td_event_views 清单的每个视图实时查 $part_event 去重码+当日次数，左连本地别名。
- save_aliases：批量 upsert (view, event_code)→display_name，空串=清除别名。
事件列表按天实时查 TD（3 表各一次）；别名与日期无关、永久存 td_event_alias。
"""

from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.td_event_alias import TdEventAlias
from app.services import config_service, ops_data

logger = logging.getLogger(__name__)

# view 未配置时的兜底（与迁移 024 seed 一致）
_DEFAULT_VIEWS = [
    {"view": "v_event_4", "product": "盒子"},
    {"view": "v_event_5", "product": "游戏"},
    {"view": "v_event_6", "product": "APP"},
]


def _resolve_views(raw: Any) -> list[dict[str, str]]:
    """td_event_views 容错解析：JSON 串/列表/缺失都归一为 [{view, product}]。"""
    if isinstance(raw, str) and raw.strip():
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("td_event_views 非法 JSON，回退默认视图")
            return list(_DEFAULT_VIEWS)
    if isinstance(raw, list):
        out = [
            {"view": str(v["view"]), "product": str(v.get("product") or v["view"])}
            for v in raw
            if isinstance(v, dict) and v.get("view")
        ]
        return out or list(_DEFAULT_VIEWS)
    return list(_DEFAULT_VIEWS)


async def _aliases_for(db: AsyncSession, view: str) -> dict[str, str]:
    """某视图下 event_code → display_name（未删除）。"""
    stmt = select(TdEventAlias).where(
        TdEventAlias.view == view, TdEventAlias.is_delete.is_(False)
    )
    return {a.event_code: a.display_name for a in (await db.execute(stmt)).scalars()}


async def list_events(db: AsyncSession, stat_date: date) -> list[dict[str, Any]]:
    """列出各视图当日全部事件码+次数，合并已存中文别名。单表失败转 error 不阻断其余。"""
    from app.integrations.thinkingdata.client import ThinkingDataClient

    cfg = await ops_data._resolve_td_config(db)
    views = _resolve_views(await config_service.resolve(db, "td_event_views", None))
    if not cfg["base_url"] or not cfg["api_secret"]:
        return [{"view": v["view"], "product": v["product"], "events": [],
                 "error": "未配置 TD 地址/密钥"} for v in views]

    client = ThinkingDataClient(base_url=cfg["base_url"], api_secret=cfg["api_secret"])
    d = stat_date.isoformat()
    out: list[dict[str, Any]] = []
    try:
        for v in views:
            view = v["view"]
            block: dict[str, Any] = {"view": view, "product": v["product"], "events": []}
            try:
                sql = (
                    f'select "$part_event" as ev, count(*) as cnt '
                    f'from {view} where "$part_date" = \'{d}\' '
                    f'group by "$part_event" order by cnt desc'
                )
                rows = await client.query_sql(sql)
                aliases = await _aliases_for(db, view)
                block["events"] = [
                    {
                        "event_code": str(r.get("ev") or ""),
                        "count": int(r.get("cnt") or 0),
                        "display_name": aliases.get(str(r.get("ev") or ""), ""),
                    }
                    for r in rows
                    if r.get("ev")
                ]
            except Exception as exc:  # noqa: BLE001 - 单表失败隔离，不阻断其余视图
                logger.warning("列事件失败 view=%s：%s", view, exc)
                block["error"] = str(exc)[:200]
            out.append(block)
    finally:
        await client.close()
    return out


async def save_aliases(db: AsyncSession, items: list[dict[str, str]]) -> int:
    """批量 upsert (view, event_code)→display_name。display_name 空串=软删清除别名。"""
    n = 0
    for it in items:
        view = (it.get("view") or "").strip()
        code = (it.get("event_code") or "").strip()
        name = (it.get("display_name") or "").strip()
        if not view or not code:
            continue
        existing = (
            await db.execute(
                select(TdEventAlias).where(
                    TdEventAlias.view == view,
                    TdEventAlias.event_code == code,
                    TdEventAlias.is_delete.is_(False),
                )
            )
        ).scalar_one_or_none()
        if not name:  # 清除别名
            if existing is not None:
                existing.is_delete = True
                n += 1
            continue
        if existing is None:
            db.add(TdEventAlias(view=view, event_code=code, display_name=name))
        else:
            existing.display_name = name
        n += 1
    await db.commit()
    return n
