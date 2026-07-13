"""agent_role → AI 员工：code/tier/title/report_to/is_seed + 部分唯一（F1）

Revision ID: 011_agent_employee
Revises: 010_org_tree
Create Date: 2026-07-13

现有 2 种子归位并赋稳定 code：运营AI总监=dir_platform_ops(director)、
会商AI专家=agent_meeting_expert(公司级共享推理体)。部门挂接由 org_template 种子服务完成。
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "011_agent_employee"
down_revision: str | None = "010_org_tree"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ACTIVE = "is_delete = false"


def upgrade() -> None:
    op.add_column("agent_role", sa.Column("code", sa.String(64), nullable=True))
    op.add_column(
        "agent_role", sa.Column("title", sa.String(64), nullable=False, server_default="")
    )
    op.add_column(
        "agent_role", sa.Column("tier", sa.String(16), nullable=False, server_default="member")
    )
    op.add_column("agent_role", sa.Column("report_to_id", sa.Uuid(), nullable=True))
    op.add_column(
        "agent_role", sa.Column("is_seed", sa.Boolean(), nullable=False, server_default="false")
    )
    op.create_foreign_key(
        "agent_role_report_to_id_fkey", "agent_role", "agent_role", ["report_to_id"], ["id"]
    )

    # name 唯一 → 部分唯一 + code 部分唯一
    op.execute('ALTER TABLE agent_role DROP CONSTRAINT IF EXISTS "agent_role_name_key"')
    op.create_index(
        "uq_agent_name", "agent_role", ["name"], unique=True, postgresql_where=sa.text(_ACTIVE)
    )
    op.create_index(
        "uq_agent_code", "agent_role", ["code"], unique=True, postgresql_where=sa.text(_ACTIVE)
    )
    op.create_index("ix_agent_dept", "agent_role", ["department_id"])

    # 现有 2 种子归位（赋稳定 code + tier + is_seed；部门挂接留给 org_template 服务）
    op.execute(
        "UPDATE agent_role SET code='dir_platform_ops', tier='director', "
        "title='平台运营部总监', is_seed=true WHERE name='运营AI总监'"
    )
    op.execute(
        "UPDATE agent_role SET code='agent_meeting_expert', tier='member', "
        "title='会商AI专家', is_seed=true WHERE name='会商AI专家'"
    )


def downgrade() -> None:
    op.drop_index("ix_agent_dept", table_name="agent_role")
    op.drop_index("uq_agent_code", table_name="agent_role")
    op.drop_index("uq_agent_name", table_name="agent_role")
    op.create_index("agent_role_name_key", "agent_role", ["name"], unique=True)
    op.drop_constraint("agent_role_report_to_id_fkey", "agent_role", type_="foreignkey")
    for col in ("is_seed", "report_to_id", "tier", "title", "code"):
        op.drop_column("agent_role", col)
