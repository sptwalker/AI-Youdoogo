"""meeting: 会议 + 讨论 + 投票 + 决议（docs/03 §3.5，阶段4 下半场）

Revision ID: 009_meeting
Revises: 008_agent_feedback
Create Date: 2026-07-13

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "009_meeting"
down_revision: str | None = "008_agent_feedback"
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
        "meeting_info",
        *_common_columns(),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("meeting_type", sa.String(32), nullable=False, server_default="decision"),
        sa.Column("status", sa.String(16), nullable=False, server_default="scheduled"),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("creator_id", sa.Uuid(), sa.ForeignKey("sys_user.id"), nullable=False),
        sa.Column(
            "participants", postgresql.JSONB(), nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("summary", sa.Text(), nullable=True),
    )
    op.create_table(
        "meeting_discuss",
        *_common_columns(),
        sa.Column("meeting_id", sa.Uuid(), sa.ForeignKey("meeting_info.id"), nullable=False),
        sa.Column("speaker_type", sa.String(8), nullable=False),
        sa.Column("speaker_id", sa.Uuid(), nullable=True),
        sa.Column("speaker_name", sa.String(64), nullable=False, server_default=""),
        sa.Column("content", sa.Text(), nullable=False),
    )
    op.create_index("ix_discuss_meeting", "meeting_discuss", ["meeting_id", "create_time"])
    op.create_table(
        "meeting_vote",
        *_common_columns(),
        sa.Column("meeting_id", sa.Uuid(), sa.ForeignKey("meeting_info.id"), nullable=False),
        sa.Column("subject", sa.String(200), nullable=False),
        sa.Column("voter_type", sa.String(8), nullable=False),
        sa.Column("voter_id", sa.Uuid(), nullable=True),
        sa.Column("choice", sa.String(16), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
    )
    op.create_index("ix_vote_meeting", "meeting_vote", ["meeting_id"])
    op.create_table(
        "meeting_resolution",
        *_common_columns(),
        sa.Column("meeting_id", sa.Uuid(), sa.ForeignKey("meeting_info.id"), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("is_confirmed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("confirmed_by", sa.Uuid(), nullable=True),
        sa.Column("converted_task_id", sa.Uuid(), nullable=True),
    )
    op.create_index("ix_resolution_meeting", "meeting_resolution", ["meeting_id"])


def downgrade() -> None:
    op.drop_index("ix_resolution_meeting", table_name="meeting_resolution")
    op.drop_table("meeting_resolution")
    op.drop_index("ix_vote_meeting", table_name="meeting_vote")
    op.drop_table("meeting_vote")
    op.drop_index("ix_discuss_meeting", table_name="meeting_discuss")
    op.drop_table("meeting_discuss")
    op.drop_table("meeting_info")
