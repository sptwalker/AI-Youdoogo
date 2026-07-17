"""semantic layer: 建 semantic_term 术语字典表 + 从 TdEventAlias 导入指标种子

Revision ID: 029_semantic_term
Revises: 028_rerank_provider
Create Date: 2026-07-17

统一语义层（docs/15 §4.2）:泛化 TdEventAlias 为通用术语字典。
建表 semantic_term（规范名唯一）+ 可选把已有事件别名导入为 metric 种子
（按 display_name 归并，event_code 收进 aliases，view 作 linked_view）——
让口径统一开箱即有存量数据;字典为空也不影响（导入 0 行）。
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "029_semantic_term"
down_revision: str | None = "028_rerank_provider"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "semantic_term",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("canonical_name", sa.String(128), nullable=False),
        sa.Column("aliases", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("term_type", sa.String(16), nullable=False, server_default="metric"),
        sa.Column("definition", sa.Text(), nullable=True),
        sa.Column("linked_view", sa.String(64), nullable=True),
        sa.Column("sql_template", sa.Text(), nullable=True),
        sa.Column("kb_refs", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("department_id", sa.Uuid(), sa.ForeignKey("sys_department.id"), nullable=True),
        sa.Column("create_time", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("update_time", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_delete", sa.Boolean(), server_default="false", nullable=False),
    )
    op.create_index(
        "uq_semantic_canonical", "semantic_term", ["canonical_name"],
        unique=True, postgresql_where=sa.text("is_delete = false"),
    )
    # 从已有事件别名导入指标种子:按中文名归并，同名多视图的事件码合进 aliases，取一个视图作关联。
    op.execute(
        sa.text(
            "INSERT INTO semantic_term "
            "(id, canonical_name, aliases, term_type, linked_view, kb_refs, "
            " is_delete, create_time, update_time) "
            "SELECT gen_random_uuid(), display_name, "
            "       to_jsonb(array_agg(DISTINCT event_code)), 'metric', min(view), "
            "       '[]'::jsonb, false, now(), now() "
            "FROM td_event_alias WHERE is_delete = false "
            "GROUP BY display_name"
        )
    )


def downgrade() -> None:
    op.drop_index("uq_semantic_canonical", table_name="semantic_term")
    op.drop_table("semantic_term")
