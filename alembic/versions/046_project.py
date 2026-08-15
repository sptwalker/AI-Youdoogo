"""046: project 表（docs/27 阶段 A1）——个人工作台项目聚合，归 project_management Context 所有。

status=active|archived（归档为软标记，非删除）。owner_id+status 复合索引服务「我的项目按态过滤」。
"""

import sqlalchemy as sa

from alembic import op

revision: str = "046_project"
down_revision: str | None = "045_marketing_sentiment_template_full"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "create_time", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column(
            "update_time", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column(
            "is_delete", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column(
            "owner_id", sa.Uuid(), sa.ForeignKey("sys_user.id"), nullable=False
        ),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "status", sa.String(length=16), nullable=False, server_default="active"
        ),
        sa.Column(
            "department_id",
            sa.Uuid(),
            sa.ForeignKey("sys_department.id"),
            nullable=True,
        ),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_project_owner_status", "project", ["owner_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_project_owner_status", table_name="project")
    op.drop_table("project")
