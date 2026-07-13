"""collab_authorization + collab_request（docs/13 §2.2 · F4c）

Revision ID: 016_collab
Revises: 015_resource_grant
Create Date: 2026-07-13

跨部门协作治理（只做结构）：既定工作流授权容器 + 主管复核队列载体。
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "016_collab"
down_revision: str | None = "015_resource_grant"
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
        "collab_authorization",
        *_common_columns(),
        sa.Column("source_department_id", sa.Uuid(), sa.ForeignKey("sys_department.id"),
                  nullable=False),
        sa.Column("target_department_id", sa.Uuid(), sa.ForeignKey("sys_department.id"),
                  nullable=False),
        sa.Column("collab_type", sa.String(64), nullable=False),
        sa.Column("authorized_by", sa.Uuid(), sa.ForeignKey("sys_user.id"), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
    )
    op.create_index(
        "ix_collab_auth_pair", "collab_authorization",
        ["source_department_id", "target_department_id"],
    )

    op.create_table(
        "collab_request",
        *_common_columns(),
        sa.Column("source_department_id", sa.Uuid(), sa.ForeignKey("sys_department.id"),
                  nullable=True),
        sa.Column("target_department_id", sa.Uuid(), sa.ForeignKey("sys_department.id"),
                  nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("category", sa.String(64), nullable=True),
        sa.Column("risk_level", sa.String(16), nullable=False, server_default="low"),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("requested_by", sa.Uuid(), nullable=True),
        sa.Column("reviewed_by", sa.Uuid(), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("ref_type", sa.String(16), nullable=True),
        sa.Column("ref_id", sa.Uuid(), nullable=True),
    )
    op.create_index(
        "ix_collab_req_target", "collab_request", ["target_department_id", "status"]
    )


def downgrade() -> None:
    op.drop_index("ix_collab_req_target", table_name="collab_request")
    op.drop_table("collab_request")
    op.drop_index("ix_collab_auth_pair", table_name="collab_authorization")
    op.drop_table("collab_authorization")
