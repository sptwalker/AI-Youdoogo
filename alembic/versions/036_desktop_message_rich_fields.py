"""desktop message rich fields: reply / attachments / pin metadata

Revision ID: 036_desktop_message_rich_fields
Revises: 035_channel_member
Create Date: 2026-07-24

桌面对话补齐企业微信式基础能力：
- reply_to_message_id + reply_preview_*：单层引用预览
- attachments：图片/文件附件元数据
- is_pinned / pinned_at / pinned_by_user_id：置顶消息
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "036_desktop_message_rich_fields"
down_revision: str | None = "035_channel_member"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "desktop_message",
        sa.Column(
            "reply_to_message_id",
            sa.Uuid(),
            sa.ForeignKey("desktop_message.id"),
            nullable=True,
        ),
    )
    op.add_column(
        "desktop_message",
        sa.Column("reply_preview_speaker_name", sa.String(64), nullable=True),
    )
    op.add_column(
        "desktop_message",
        sa.Column("reply_preview_content", sa.Text(), nullable=True),
    )
    op.add_column(
        "desktop_message",
        sa.Column("attachments", postgresql.JSONB(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "desktop_message",
        sa.Column("is_pinned", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "desktop_message",
        sa.Column("pinned_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "desktop_message",
        sa.Column(
            "pinned_by_user_id",
            sa.Uuid(),
            sa.ForeignKey("sys_user.id"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_desktop_msg_owner_pinned",
        "desktop_message",
        ["owner_user_id", "is_pinned", "pinned_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_desktop_msg_owner_pinned", table_name="desktop_message")
    op.drop_column("desktop_message", "pinned_by_user_id")
    op.drop_column("desktop_message", "pinned_at")
    op.drop_column("desktop_message", "is_pinned")
    op.drop_column("desktop_message", "attachments")
    op.drop_column("desktop_message", "reply_preview_content")
    op.drop_column("desktop_message", "reply_preview_speaker_name")
    op.drop_column("desktop_message", "reply_to_message_id")
