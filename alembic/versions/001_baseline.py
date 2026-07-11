"""baseline: sys_user / sys_department / sys_role

Revision ID: 001_baseline
Revises:
Create Date: 2026-07-11

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "001_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _common_columns() -> list[sa.Column]:
    """文档03通用基础字段。"""
    return [
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("create_time", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("update_time", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_delete", sa.Boolean(), server_default="false", nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "sys_department",
        *_common_columns(),
        sa.Column("name", sa.String(64), nullable=False, unique=True),
        sa.Column("code", sa.String(32), nullable=False, unique=True),
    )
    op.create_table(
        "sys_role",
        *_common_columns(),
        sa.Column("code", sa.String(32), nullable=False, unique=True),
        sa.Column("name", sa.String(64), nullable=False),
    )
    op.create_table(
        "sys_user",
        *_common_columns(),
        sa.Column("username", sa.String(64), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("real_name", sa.String(64), nullable=False, server_default=""),
        sa.Column("role_code", sa.String(32), nullable=False, server_default="member"),
        sa.Column(
            "department_id", sa.Uuid(), sa.ForeignKey("sys_department.id"), nullable=True
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
    )
    # 首版三角色字典
    op.execute(
        "INSERT INTO sys_role (id, code, name) VALUES "
        "(gen_random_uuid(), 'admin', '超级管理员'), "
        "(gen_random_uuid(), 'executive', '高管'), "
        "(gen_random_uuid(), 'member', '成员')"
    )


def downgrade() -> None:
    op.drop_table("sys_user")
    op.drop_table("sys_role")
    op.drop_table("sys_department")
