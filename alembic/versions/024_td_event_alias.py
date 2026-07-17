"""td event alias: 建事件别名表 + seed td_event_views 视图清单

Revision ID: 024_td_event_alias
Revises: 023_deliverable
Create Date: 2026-07-16

运营事件自定义命名（数据接口页）：事件码→中文显示名，别名按视图分。
顺带 seed 可编辑配置 td_event_views：哪些 TD 视图算「产品」（供事件枚举与运营取数复用）。
"""
import json
import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "024_td_event_alias"
down_revision: str | None = "023_deliverable"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_VIEWS = json.dumps(
    [
        {"view": "v_event_4", "product": "盒子"},
        {"view": "v_event_5", "product": "游戏"},
        {"view": "v_event_6", "product": "APP"},
    ],
    ensure_ascii=False,
)


def upgrade() -> None:
    op.create_table(
        "td_event_alias",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("view", sa.String(64), nullable=False),
        sa.Column("event_code", sa.String(128), nullable=False),
        sa.Column("display_name", sa.String(128), nullable=False),
        sa.Column("create_time", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("update_time", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_delete", sa.Boolean(), server_default="false", nullable=False),
    )
    op.create_index(
        "uq_td_event_alias", "td_event_alias", ["view", "event_code"],
        unique=True, postgresql_where=sa.text("is_delete = false"),
    )
    op.execute(
        sa.text(
            "INSERT INTO sys_config "
            "(id, key, value, value_type, category, is_editable, is_secret, is_delete, "
            "create_time, update_time) VALUES "
            "(:id, 'td_event_views', to_jsonb(CAST(:val AS text)), 'text', 'dataif', true, "
            "false, false, now(), now())"
        ).bindparams(id=uuid.uuid4(), val=_VIEWS)
    )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM sys_config WHERE key = 'td_event_views'"))
    op.drop_index("uq_td_event_alias", table_name="td_event_alias")
    op.drop_table("td_event_alias")
