"""047: task_card 挂 project_id + archived_at（docs/27 阶段 A2）。

纯加两列可空：project_id（FK project.id，个人工作台归属项目）+ archived_at（归档软标记，
与状态机正交）。历史行取 NULL。project_id 建索引服务「按项目筛选」。
"""

import sqlalchemy as sa

from alembic import op

revision: str = "047_task_project_archive"
down_revision: str | None = "046_project"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "task_card",
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("project.id"), nullable=True),
    )
    op.add_column(
        "task_card",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_task_card_project", "task_card", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_task_card_project", table_name="task_card")
    op.drop_column("task_card", "archived_at")
    op.drop_column("task_card", "project_id")
