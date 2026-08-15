"""049: 个人知识库归真人 knowledge_base.owner_user_id（docs/27 阶段 B1）。

个人库（scope=personal）落 owner_user_id=本人；公司/部门库留 NULL。
检索隔离复用既有 visible_kb_ids 杠杆，本迁移仅补归属列 + owner 索引。
"""

import sqlalchemy as sa

from alembic import op

revision: str = "049_knowledge_base_owner"
down_revision: str | None = "048_inbox_item_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "knowledge_base",
        sa.Column("owner_user_id", sa.Uuid(), sa.ForeignKey("sys_user.id"), nullable=True),
    )
    op.create_index("ix_kb_owner_user", "knowledge_base", ["owner_user_id"])


def downgrade() -> None:
    op.drop_index("ix_kb_owner_user", table_name="knowledge_base")
    op.drop_column("knowledge_base", "owner_user_id")
