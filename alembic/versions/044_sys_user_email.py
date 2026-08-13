"""sys_user 加 email 列（docs/26 P3/P4，会商通知 + send_email 能力收件人来源）

Revision ID: 044_sys_user_email
Revises: 043_marketing_sentiment_template
Create Date: 2026-08-13

加法式：sys_user 加 nullable email 列。飞书同步/管理员填，未知则空——convene/send_email
执行器据此如实声明并安全跳过，不臆造地址。无索引（非登录键、非唯一约束，与 mobile 一致不建索引）。
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "044_sys_user_email"
down_revision: str | None = "043_marketing_sentiment_template"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sys_user",
        sa.Column("email", sa.String(255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sys_user", "email")
