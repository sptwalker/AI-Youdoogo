"""task_card: 任务卡主表 + 流转日志（docs/03 §3.3，阶段3）

Revision ID: 006_task_card
Revises: 005_ops_daily_metric
Create Date: 2026-07-12

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "006_task_card"
down_revision: str | None = "005_ops_daily_metric"
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
        "task_card",
        *_common_columns(),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("task_type", sa.String(32), nullable=False),
        sa.Column("priority", sa.String(16), nullable=False, server_default="normal"),
        sa.Column("status", sa.String(24), nullable=False, server_default="created"),
        sa.Column("creator_id", sa.Uuid(), sa.ForeignKey("sys_user.id"), nullable=False),
        sa.Column(
            "assignee_agent_id", sa.Uuid(), sa.ForeignKey("agent_role.id"), nullable=True
        ),
        sa.Column("parent_id", sa.Uuid(), sa.ForeignKey("task_card.id"), nullable=True),
        sa.Column("sla_hours", sa.Integer(), nullable=True),
        sa.Column(
            "payload", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("result_content", sa.Text(), nullable=True),
    )
    op.create_index("ix_task_status", "task_card", ["status"])
    op.create_index("ix_task_parent", "task_card", ["parent_id"])
    op.create_table(
        "task_card_log",
        *_common_columns(),
        sa.Column("task_id", sa.Uuid(), sa.ForeignKey("task_card.id"), nullable=False),
        sa.Column("from_status", sa.String(24), nullable=True),
        sa.Column("to_status", sa.String(24), nullable=False),
        sa.Column("operator_id", sa.Uuid(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
    )
    op.create_index("ix_tasklog_task", "task_card_log", ["task_id", "create_time"])


def downgrade() -> None:
    op.drop_index("ix_tasklog_task", table_name="task_card_log")
    op.drop_table("task_card_log")
    op.drop_index("ix_task_parent", table_name="task_card")
    op.drop_index("ix_task_status", table_name="task_card")
    op.drop_table("task_card")
