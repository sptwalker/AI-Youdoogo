"""org tree: sys_department 树化 + 公司根 + 软删唯一约束系统性修复（F1）

Revision ID: 010_org_tree
Revises: 009_meeting
Create Date: 2026-07-13

把"公司"建成组织树根节点；现有扁平部门归为一级；业务唯一键统一改为
"部分唯一索引 WHERE is_delete=false"（修复软删后重建同名撞库）。CEO=最高管理员(真人)。
"""
import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "010_org_tree"
down_revision: str | None = "009_meeting"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ACTIVE = "is_delete = false"


def _to_partial_unique(table: str, col: str, old_constraint: str, new_index: str) -> None:
    """把列级 unique 约束换成部分唯一索引（排除软删行）。"""
    op.execute(f'ALTER TABLE {table} DROP CONSTRAINT IF EXISTS "{old_constraint}"')
    op.create_index(new_index, table, [col], unique=True, postgresql_where=sa.text(_ACTIVE))


def upgrade() -> None:
    # 1) sys_department 树化列
    op.add_column("sys_department", sa.Column("parent_id", sa.Uuid(), nullable=True))
    op.add_column(
        "sys_department",
        sa.Column("node_type", sa.String(16), nullable=False, server_default="dept_l1"),
    )
    op.add_column(
        "sys_department", sa.Column("level", sa.SmallInteger(), nullable=False, server_default="1")
    )
    op.add_column(
        "sys_department", sa.Column("path", sa.String(255), nullable=False, server_default="")
    )
    op.add_column(
        "sys_department", sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column("sys_department", sa.Column("supervisor_user_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "sys_department_parent_id_fkey", "sys_department", "sys_department",
        ["parent_id"], ["id"],
    )
    op.create_foreign_key(
        "fk_dept_supervisor", "sys_department", "sys_user", ["supervisor_user_id"], ["id"],
    )

    # 2) 建公司根节点 + 现有部门归为一级（parent=根、level=1、回填 path）
    root_id = uuid.uuid4()
    op.execute(
        sa.text(
            "INSERT INTO sys_department "
            "(id, name, code, node_type, level, path, sort_order, is_delete, "
            "create_time, update_time) "
            "VALUES (:id, :name, 'company', 'company', 0, :path, 0, false, now(), now())"
        ).bindparams(id=root_id, name="创想悦动", path=f"/{root_id}/")
    )
    op.execute(
        sa.text(
            "UPDATE sys_department SET parent_id=:root, node_type='dept_l1', level=1, "
            "path='/' || :root_str || '/' || id::text || '/' WHERE id <> :root"
        ).bindparams(root=root_id, root_str=str(root_id))
    )

    # 3) 部门唯一约束 → 部分唯一（同父名唯一 + code 全局唯一）
    op.execute('ALTER TABLE sys_department DROP CONSTRAINT IF EXISTS "sys_department_name_key"')
    op.execute('ALTER TABLE sys_department DROP CONSTRAINT IF EXISTS "sys_department_code_key"')
    op.create_index(
        "uq_dept_parent_name", "sys_department", ["parent_id", "name"], unique=True,
        postgresql_where=sa.text(_ACTIVE),
    )
    op.create_index(
        "uq_dept_code", "sys_department", ["code"], unique=True, postgresql_where=sa.text(_ACTIVE)
    )
    op.create_index("ix_dept_path", "sys_department", ["path"])
    op.create_index("ix_dept_parent", "sys_department", ["parent_id"])

    # 4) 其余业务唯一键系统性修复（agent_role 在 011）
    _to_partial_unique("sys_user", "username", "sys_user_username_key", "uq_user_username")
    _to_partial_unique("sys_role", "code", "sys_role_code_key", "uq_role_code")
    _to_partial_unique("proposal_card", "code", "proposal_card_code_key", "uq_proposal_code")


def downgrade() -> None:
    for idx in ("uq_user_username", "uq_role_code", "uq_proposal_code"):
        op.drop_index(idx)
    op.drop_index("ix_dept_parent", table_name="sys_department")
    op.drop_index("ix_dept_path", table_name="sys_department")
    op.drop_index("uq_dept_code", table_name="sys_department")
    op.drop_index("uq_dept_parent_name", table_name="sys_department")
    # 先 drop 自引用 FK，再删根节点——否则子部门 parent_id 仍指向根，删根违反外键
    op.drop_constraint("fk_dept_supervisor", "sys_department", type_="foreignkey")
    op.drop_constraint("sys_department_parent_id_fkey", "sys_department", type_="foreignkey")
    op.execute("DELETE FROM sys_department WHERE node_type='company'")
    for col in ("supervisor_user_id", "sort_order", "path", "level", "node_type", "parent_id"):
        op.drop_column("sys_department", col)
