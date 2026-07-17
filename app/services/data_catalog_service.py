"""数据目录:把「有哪些数据源/视图/事件、各是什么含义」聚成 AI 可读目录。

目录三源(全部复用现有):
- DataSource(data_source 表):type=thinkingdata 的数据接口 + 对接 AI。
- td_event_views(sys_config):哪些 TD 视图算「产品」。
- TdEventAlias(td_event_alias 表):事件码 → 中文别名。
供:①白名单(取数护栏用哪些视图合法)②提示词段(agent 知道能查什么、字段含义)③外部 MCP 的 resources。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import DataSource
from app.models.td_event_alias import TdEventAlias
from app.services import config_service
from app.services.td_event_service import _resolve_views


async def _td_sources(db: AsyncSession) -> list[dict[str, str]]:
    """已登记的 ThinkingData 数据接口(名称/编码/是否启用)。"""
    stmt = select(DataSource).where(
        DataSource.type == "thinkingdata", DataSource.is_delete.is_(False)
    )
    return [
        {"name": d.name, "code": d.code, "active": "是" if d.is_active else "否"}
        for d in (await db.execute(stmt)).scalars()
    ]


async def allowed_views(db: AsyncSession) -> set[str]:
    """取数护栏的视图白名单 = td_event_views 清单里的视图名(小写)。"""
    views = _resolve_views(await config_service.resolve(db, "td_event_views", None))
    return {v["view"].lower() for v in views}


async def get_catalog(db: AsyncSession) -> dict[str, Any]:
    """结构化数据目录:数据源 + 视图→产品 + 每视图已命名事件。"""
    views = _resolve_views(await config_service.resolve(db, "td_event_views", None))
    # 一次拉全部别名，按视图分组(避免逐视图查库)
    aliases = (
        await db.execute(select(TdEventAlias).where(TdEventAlias.is_delete.is_(False)))
    ).scalars()
    by_view: dict[str, list[dict[str, str]]] = {}
    for a in aliases:
        by_view.setdefault(a.view, []).append(
            {"event_code": a.event_code, "display_name": a.display_name}
        )
    return {
        "sources": await _td_sources(db),
        "views": [
            {
                "view": v["view"],
                "product": v["product"],
                "named_events": by_view.get(v["view"], []),
            }
            for v in views
        ],
    }


async def catalog_prompt(db: AsyncSession) -> str:
    """把目录渲染成 agent 提示词段(供取数技能注入)。无视图返回空串。"""
    cat = await get_catalog(db)
    if not cat["views"]:
        return ""
    lines = ["\n\n【可查数据(ThinkingData)】你可用只读 SQL 查询以下视图(仅 SELECT，会自动限行):"]
    for v in cat["views"]:
        head = f"- {v['product']}:视图 {v['view']}"
        if v["named_events"]:
            evs = "、".join(
                f"{e['event_code']}={e['display_name']}" for e in v["named_events"][:20]
            )
            head += f"；已命名事件:{evs}"
        lines.append(head)
    lines.append(
        "取数写法(ThinkingData/Presto，务必遵守，否则会被拒):\n"
        "1. WHERE 必须带日期分区 \"$part_date\"，否则报「请带上日期分区字段」。"
        "单日用 \"$part_date\"='YYYY-MM-DD'；"
        "区间用 \"$part_date\" BETWEEN 'YYYY-MM-DD' AND 'YYYY-MM-DD'；"
        "累计/全量统计也要给足够宽的范围，如 \"$part_date\">='2020-01-01'（不可省略）。\n"
        "2. 事件名用 \"$part_event\"，用户去重用 count(distinct \"#user_id\")。\n"
        "3. 列别名含中文/非英文必须加双引号，如 AS \"累计激活设备数\"；"
        "裸中文别名会报 mismatched input；纯英文别名可不加引号。\n"
        "4. 只能查上表列出的视图，且只能 SELECT。"
    )
    return "\n".join(lines)
