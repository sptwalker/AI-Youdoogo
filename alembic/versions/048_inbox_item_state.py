"""048: 收件箱条目读态表 inbox_item_state（docs/27 阶段 A4）。

按 (owner_user_id, kind, source_id) 落已读/已处理/AI 摘要持久态；唯一索引服务 upsert 去重。
source_id 跨多张来源表软引用，不加外键。
"""

import sqlalchemy as sa

from alembic import op

revision: str = "048_inbox_item_state"
down_revision: str | None = "047_task_project_archive"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "inbox_item_state",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("owner_user_id", sa.Uuid(), sa.ForeignKey("sys_user.id"), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("is_read", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("is_processed", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("ai_summary", sa.Text(), nullable=True),
        sa.Column("create_time", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("update_time", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_delete", sa.Boolean(), server_default="false", nullable=False),
    )
    op.create_index(
        "uq_inbox_owner_source",
        "inbox_item_state",
        ["owner_user_id", "kind", "source_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_inbox_owner_source", table_name="inbox_item_state")
    op.drop_table("inbox_item_state")
