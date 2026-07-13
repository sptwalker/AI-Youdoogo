"""knowledge_base + data_source + knowledge_file.knowledge_base_id（docs/13 F2）

Revision ID: 012_knowledge_base
Revises: 011_agent_employee
Create Date: 2026-07-13

知识集合化：建 knowledge_base/data_source；knowledge_file 加 knowledge_base_id。
安全默认：种子"公司公共库"，存量文件全部回填该库(全员可见)，再置 NOT NULL。
"""
import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "012_knowledge_base"
down_revision: str | None = "011_agent_employee"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ACTIVE = "is_delete = false"


def _common_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("create_time", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("update_time", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_delete", sa.Boolean(), server_default="false", nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "knowledge_base",
        *_common_columns(),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("scope", sa.String(16), nullable=False, server_default="department"),
        sa.Column("department_id", sa.Uuid(), sa.ForeignKey("sys_department.id"), nullable=True),
        sa.Column("owner_agent_id", sa.Uuid(), sa.ForeignKey("agent_role.id"), nullable=True),
        sa.Column("is_confidential", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
    )
    op.create_index("uq_kb_code", "knowledge_base", ["code"], unique=True,
                    postgresql_where=sa.text(_ACTIVE))
    op.create_table(
        "data_source",
        *_common_columns(),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("department_id", sa.Uuid(), sa.ForeignKey("sys_department.id"), nullable=True),
        sa.Column("config", sa.dialects.postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("secret_ref", sa.String(128), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
    )
    op.create_index("uq_ds_code", "data_source", ["code"], unique=True,
                    postgresql_where=sa.text(_ACTIVE))

    # 种子：公司公共库（scope=company, default）
    kb_id = uuid.uuid4()
    op.execute(
        sa.text(
            "INSERT INTO knowledge_base "
            "(id, name, code, scope, is_confidential, is_default, is_active, "
            "is_delete, create_time, update_time) VALUES "
            "(:id, :name, 'kb_company_public', 'company', false, true, true, "
            "false, now(), now())"
        ).bindparams(id=kb_id, name="公司公共知识库")
    )

    # knowledge_file 加 kb_id（先 nullable）→ 回填存量文件到公司公共库 → NOT NULL
    op.add_column("knowledge_file", sa.Column("knowledge_base_id", sa.Uuid(), nullable=True))
    op.execute(
        sa.text("UPDATE knowledge_file SET knowledge_base_id=:kb WHERE knowledge_base_id IS NULL")
        .bindparams(kb=kb_id)
    )
    op.alter_column("knowledge_file", "knowledge_base_id", nullable=False)
    op.create_foreign_key(
        "knowledge_file_kb_fkey", "knowledge_file", "knowledge_base",
        ["knowledge_base_id"], ["id"],
    )
    op.create_index("ix_kf_kb", "knowledge_file", ["knowledge_base_id"])


def downgrade() -> None:
    op.drop_index("ix_kf_kb", table_name="knowledge_file")
    op.drop_constraint("knowledge_file_kb_fkey", "knowledge_file", type_="foreignkey")
    op.drop_column("knowledge_file", "knowledge_base_id")
    op.drop_index("uq_ds_code", table_name="data_source")
    op.drop_table("data_source")
    op.drop_index("uq_kb_code", table_name="knowledge_base")
    op.drop_table("knowledge_base")
