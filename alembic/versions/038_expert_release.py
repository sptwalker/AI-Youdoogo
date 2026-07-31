"""expert_release: 专家执行定义不可变发布快照 + agent_role 发布软指针（Phase 3 Module 2 / docs/23）

Revision ID: 038_expert_release
Revises: 037_inbox_event
Create Date: 2026-07-31

加法式：新增只增不改的 expert_release 表 + agent_role.current_release_id 软指针（不加 FK，避免与
expert_release.expert_id 成循环外键）。不改 agent_role 现有列，97 处读路径零影响。
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "038_expert_release"
down_revision: str | None = "037_inbox_event"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "expert_release",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("create_time", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("update_time", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_delete", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("expert_id", sa.Uuid(), sa.ForeignKey("agent_role.id"), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("prompt_template", sa.Text(), nullable=False),
        sa.Column("model_role", sa.String(32), nullable=False),
        sa.Column("permission_scope", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("tools", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("duty", sa.Text(), nullable=True),
        sa.Column("released_by", sa.Uuid(), nullable=True),
    )
    op.create_index(
        "uq_expert_release_version", "expert_release", ["expert_id", "version_no"], unique=True
    )
    op.add_column("agent_role", sa.Column("current_release_id", sa.Uuid(), nullable=True))


def downgrade() -> None:
    op.drop_column("agent_role", "current_release_id")
    op.drop_index("uq_expert_release_version", table_name="expert_release")
    op.drop_table("expert_release")
