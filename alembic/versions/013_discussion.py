"""discussion_channel + discussion_message + meeting_info.department_id（docs/13 F3'）

Revision ID: 013_discussion
Revises: 012_knowledge_base
Create Date: 2026-07-13

协作空间：建讨论频道/消息两表；meeting_info 加 department_id（存量会议 NULL=临时会议）。
安全默认：为公司根 + 每个现有部门各种子一个「{部门名}讨论区」频道。
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "013_discussion"
down_revision: str | None = "012_knowledge_base"
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
        "discussion_channel",
        *_common_columns(),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("department_id", sa.Uuid(), sa.ForeignKey("sys_department.id"), nullable=True),
        sa.Column("default_agent_id", sa.Uuid(), sa.ForeignKey("agent_role.id"), nullable=True),
        sa.Column("creator_id", sa.Uuid(), sa.ForeignKey("sys_user.id"), nullable=True),
        sa.Column("is_archived", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.create_table(
        "discussion_message",
        *_common_columns(),
        sa.Column(
            "channel_id", sa.Uuid(), sa.ForeignKey("discussion_channel.id"), nullable=False
        ),
        sa.Column("speaker_type", sa.String(8), nullable=False),
        sa.Column("speaker_id", sa.Uuid(), nullable=True),
        sa.Column("speaker_name", sa.String(64), nullable=False, server_default=""),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("mentioned_agent_ids", sa.dialects.postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("ai_source_record_id", sa.Uuid(), nullable=True),
        sa.Column("ref_type", sa.String(16), nullable=True),
        sa.Column("ref_id", sa.Uuid(), nullable=True),
    )
    op.create_index("ix_dm_channel", "discussion_message", ["channel_id", "create_time"])

    op.add_column(
        "meeting_info", sa.Column("department_id", sa.Uuid(), nullable=True)
    )
    op.create_foreign_key(
        "meeting_info_dept_fkey", "meeting_info", "sys_department",
        ["department_id"], ["id"],
    )

    # 种子：公司根 + 每个现有部门各一个默认讨论频道
    op.execute(
        sa.text(
            "INSERT INTO discussion_channel "
            "(id, name, department_id, is_archived, is_delete, create_time, update_time) "
            "SELECT gen_random_uuid(), name || '讨论区', id, false, false, now(), now() "
            "FROM sys_department WHERE is_delete = false"
        )
    )


def downgrade() -> None:
    op.drop_constraint("meeting_info_dept_fkey", "meeting_info", type_="foreignkey")
    op.drop_column("meeting_info", "department_id")
    op.drop_index("ix_dm_channel", table_name="discussion_message")
    op.drop_table("discussion_message")
    op.drop_table("discussion_channel")
