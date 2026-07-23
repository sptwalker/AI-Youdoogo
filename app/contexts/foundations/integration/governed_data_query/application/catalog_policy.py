"""Pure catalog rendering policy shared by HTTP and Agent consumers."""

from app.contexts.foundations.integration.governed_data_query.contracts import (
    DataCatalogSnapshot,
)


def render_catalog_prompt(catalog: DataCatalogSnapshot) -> str:
    if not catalog.views:
        return ""
    lines = ["\n\n【可查数据(ThinkingData)】你可用只读 SQL 查询以下视图(仅 SELECT，会自动限行):"]
    for view in catalog.views:
        head = f"- {view.product}:视图 {view.view}"
        if view.named_events:
            events = "、".join(
                f"{event.event_code}={event.display_name}"
                for event in view.named_events[:20]
            )
            head += f"；已命名事件:{events}"
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
