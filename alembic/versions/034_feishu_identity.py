"""feishu identity: sys_department/sys_user 加飞书映射字段 + 索引（I1，docs/18）

Revision ID: 034_feishu_identity
Revises: 033_eval_case
Create Date: 2026-07-20

多人+AI即时通讯 I1 身份同步:给部门/用户加飞书通讯录映射字段。
- sys_department.feishu_open_id（open_department_id 稳定同步键）
- sys_user.en_name/title/mobile/avatar_url（同步+SSO 展示字段）
- 飞书用户 open_id 已由 019_feishu_oauth 创建，本迁移不重复添加。
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "034_feishu_identity"
down_revision: str | None = "035_durable_workflow"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ACTIVE = "is_delete = false"


def upgrade() -> None:
    op.add_column("sys_department", sa.Column("feishu_open_id", sa.String(128), nullable=True))
    op.create_index(
        "uq_dept_feishu", "sys_department", ["feishu_open_id"],
        unique=True, postgresql_where=sa.text(_ACTIVE),
    )
    op.add_column("sys_user", sa.Column("en_name", sa.String(64), nullable=False,
                                        server_default=""))
    op.add_column("sys_user", sa.Column("title", sa.String(64), nullable=False,
                                        server_default=""))
    op.add_column("sys_user", sa.Column("mobile", sa.String(32), nullable=False,
                                        server_default=""))
    op.add_column("sys_user", sa.Column("avatar_url", sa.String(512), nullable=False,
                                        server_default=""))


def downgrade() -> None:
    op.drop_column("sys_user", "avatar_url")
    op.drop_column("sys_user", "mobile")
    op.drop_column("sys_user", "title")
    op.drop_column("sys_user", "en_name")
    op.drop_index("uq_dept_feishu", table_name="sys_department")
    op.drop_column("sys_department", "feishu_open_id")
