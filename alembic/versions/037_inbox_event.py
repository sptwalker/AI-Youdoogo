"""inbox_event: 入站事件幂等去重表（Phase 3 事件传输门禁 / docs/23）

Revision ID: 037_inbox_event
Revises: 036_desktop_message_rich_fields
Create Date: 2026-07-31

跨服务事件交接的入站半边。event_id（源 outbox 事件 id）唯一约束 = 入站幂等去重键：
同一事件重复投递（网络重试 / DLQ 重放）只落一行，逻辑上只处理一次。
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "037_inbox_event"
down_revision: str | None = "036_desktop_message_rich_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "inbox_event",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("create_time", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("update_time", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_delete", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("aggregate_type", sa.String(32), nullable=False),
        sa.Column("aggregate_id", sa.Uuid(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("source_service", sa.String(128), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="received"),
    )
    op.create_index("uq_inbox_event_id", "inbox_event", ["event_id"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_inbox_event_id", table_name="inbox_event")
    op.drop_table("inbox_event")
