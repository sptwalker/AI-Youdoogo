"""种子 ThinkingData 接入的可配置项（sys_config）：地址/SQL/字段映射

Revision ID: 017_td_config
Revises: 016_collab
Create Date: 2026-07-14

运营数据接入 ThinkingData：把「TD 地址 / 每日拉取 SQL / 字段映射」做成可编辑配置
（系统配置页可改，联调时无需改代码）。密钥仍走 .env（密钥红线，此处不存）。
"""
import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "017_td_config"
down_revision: str | None = "016_collab"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DAILY_SQL = (
    "-- ThinkingData 每日运营指标（占位模板：请按你们 TD 项目替换视图名/事件名/属性名）\n"
    "-- 必须返回列：字段映射(td_field_mapping)里配置的列名，默认 product / dau / new_users\n"
    "SELECT \"产品属性\" AS product,\n"
    "       count(distinct \"#user_id\") AS dau,\n"
    "       count(distinct if(\"#event_name\"='安装事件', \"#user_id\", null)) AS new_users\n"
    "FROM v_event_你们的项目\n"
    "WHERE \"$part_date\" = '${stat_date}'\n"
    "GROUP BY \"产品属性\""
)
_FIELD_MAPPING = '{"product": "product", "dau": "dau", "new_users": "new_users"}'

_SEEDS = [
    ("td_base_url", "", "string", "TD 地址，形如 http://HOST:8992；留空则回退 .env 的 TD_BASE_URL"),
    ("td_daily_metrics_sql", _DAILY_SQL, "text", "每日拉取 SQL，${stat_date} 会被替换为统计日"),
    (
        "td_field_mapping",
        _FIELD_MAPPING,
        "text",
        "TD 结果列→本系统字段映射(JSON)：product/dau/new_users",
    ),
]


def upgrade() -> None:
    for key, val, vtype, _desc in _SEEDS:
        op.execute(
            sa.text(
                "INSERT INTO sys_config "
                "(id, key, value, value_type, category, is_editable, is_delete, "
                "create_time, update_time) VALUES "
                "(:id, :key, to_jsonb(CAST(:val AS text)), :vtype, 'dataif', true, false, "
                "now(), now())"
            ).bindparams(id=uuid.uuid4(), key=key, val=val, vtype=vtype)
        )


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM sys_config WHERE key IN "
                "('td_base_url', 'td_daily_metrics_sql', 'td_field_mapping')")
    )
