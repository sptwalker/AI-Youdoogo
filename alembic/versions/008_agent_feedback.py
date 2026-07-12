"""agent_feedback: 智能体输出反馈评分表（docs/06 阶段5）

Revision ID: 008_agent_feedback
Revises: 007_proposal
Create Date: 2026-07-12

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "008_agent_feedback"
down_revision: str | None = "007_proposal"
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
        "agent_feedback",
        *_common_columns(),
        sa.Column(
            "task_record_id", sa.Uuid(), sa.ForeignKey("agent_task_record.id"), nullable=False
        ),
        sa.Column("rater_id", sa.Uuid(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
    )
    op.create_index("ix_feedback_record", "agent_feedback", ["task_record_id"])


def downgrade() -> None:
    op.drop_index("ix_feedback_record", table_name="agent_feedback")
    op.drop_table("agent_feedback")
