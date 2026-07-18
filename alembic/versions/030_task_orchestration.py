"""task orchestration: task_card 加 step_no / depends_on / step_input（DAG 编排字段）

Revision ID: 030_task_orchestration
Revises: 029_semantic_term
Create Date: 2026-07-18

任务编排层阶段B（docs/14 §4.2）:给 TaskCard 加 DAG 步骤字段——纯加列，历史行取默认，
不破坏现有卡。step_no=步骤序号；depends_on=前序步骤卡 id 列表(DAG)；step_input=上游产出注入。
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "030_task_orchestration"
down_revision: str | None = "029_semantic_term"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("task_card", sa.Column("step_no", sa.Integer(), nullable=True))
    op.add_column(
        "task_card",
        sa.Column("depends_on", postgresql.JSONB(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "task_card",
        sa.Column("step_input", postgresql.JSONB(), nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("task_card", "step_input")
    op.drop_column("task_card", "depends_on")
    op.drop_column("task_card", "step_no")
