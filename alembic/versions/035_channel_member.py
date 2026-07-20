"""channel members: 建 channel_member 表 + discussion_message 加 attachments（I4/I6，docs/18）

Revision ID: 035_channel_member
Revises: 034_feishu_identity
Create Date: 2026-07-20

多人+AI即时通讯 I4:群成员名单（真人+AI混合）+ 未读水位 last_read_at。
顺带 I6:discussion_message 加 attachments（消息附件，纯加列历史行取默认）。
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "035_channel_member"
down_revision: str | None = "034_feishu_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "channel_member",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("channel_id", sa.Uuid(), sa.ForeignKey("discussion_channel.id"), nullable=False),
        sa.Column("member_type", sa.String(8), nullable=False),
        sa.Column("member_id", sa.Uuid(), nullable=False),
        sa.Column("member_name", sa.String(64), nullable=False, server_default=""),
        sa.Column("last_read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("create_time", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("update_time", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_delete", sa.Boolean(), server_default="false", nullable=False),
    )
    op.create_index(
        "uq_channel_member", "channel_member",
        ["channel_id", "member_type", "member_id"], unique=True,
    )
    op.create_index("ix_cm_member", "channel_member", ["member_type", "member_id"])
    op.add_column(
        "discussion_message",
        sa.Column("attachments", postgresql.JSONB(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("discussion_message", "attachments")
    op.drop_index("ix_cm_member", table_name="channel_member")
    op.drop_index("uq_channel_member", table_name="channel_member")
    op.drop_table("channel_member")
