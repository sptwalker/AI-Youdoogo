"""ops_daily_metric: 平台运营日指标表（阶段2）

Revision ID: 005_ops_daily_metric
Revises: 004_llm_call_log
Create Date: 2026-07-12

阶段4 再按 docs/03 §3.7 转 TimescaleDB hypertable（届时主键需含 stat_date）；
本阶段普通表足够。
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "005_ops_daily_metric"
down_revision: str | None = "004_llm_call_log"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _common_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("create_time", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("update_time", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_delete", sa.Boolean(), server_default="false", nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "ops_daily_metric",
        *_common_columns(),
        sa.Column("stat_date", sa.Date(), nullable=False),
        sa.Column("product", sa.String(64), nullable=False),
        sa.Column("dau", sa.Integer(), nullable=False),
        sa.Column("new_users", sa.Integer(), nullable=True),
        sa.Column("retention_d1", sa.Float(), nullable=True),
        sa.Column("source", sa.String(32), nullable=False, server_default="excel"),
        sa.UniqueConstraint("stat_date", "product", name="uq_ops_date_product"),
    )
    op.create_index("ix_ops_stat_date", "ops_daily_metric", ["stat_date"])


def downgrade() -> None:
    op.drop_index("ix_ops_stat_date", table_name="ops_daily_metric")
    op.drop_table("ops_daily_metric")
