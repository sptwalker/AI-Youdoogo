"""resource_grant 显式授权表（docs/13 §1.3 · F4b）

Revision ID: 015_resource_grant
Revises: 014_audit_config
Create Date: 2026-07-13

唯一权限例外表：默认可见性之外的显式跨节点/私有覆盖授权。
resource_id/grantee_id 多态松引用不加 FK；granted_by 关联 sys_user。
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "015_resource_grant"
down_revision: str | None = "014_audit_config"
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
        "resource_grant",
        *_common_columns(),
        sa.Column("resource_type", sa.String(32), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("grantee_type", sa.String(16), nullable=False),
        sa.Column("grantee_id", sa.Uuid(), nullable=False),
        sa.Column("perm", sa.String(16), nullable=False, server_default="read"),
        sa.Column("granted_by", sa.Uuid(), sa.ForeignKey("sys_user.id"), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_grant_lookup", "resource_grant", ["resource_type", "grantee_type", "grantee_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_grant_lookup", table_name="resource_grant")
    op.drop_table("resource_grant")
