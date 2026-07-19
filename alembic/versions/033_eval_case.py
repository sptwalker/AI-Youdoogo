"""eval cases: 建 eval_case 评估集表（评估驱动，H3.1）

Revision ID: 033_eval_case
Revises: 032_task_record_sources
Create Date: 2026-07-20

质量闭环 H3.1（docs/16）:评估驱动开发的用例库。每条=输入+评分标准(rubric)，
绑定角色(role_id 空=通用)。供 run_eval(LLM-as-Judge打分) + shadow_compare(改提示词前对比)。
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "033_eval_case"
down_revision: str | None = "032_task_record_sources"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "eval_case",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("role_id", sa.Uuid(), sa.ForeignKey("agent_role.id"), nullable=True),
        sa.Column("input_text", sa.Text(), nullable=False),
        sa.Column("rubric", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("create_time", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("update_time", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_delete", sa.Boolean(), server_default="false", nullable=False),
    )
    op.create_index("ix_eval_case_role", "eval_case", ["role_id"])


def downgrade() -> None:
    op.drop_index("ix_eval_case_role", table_name="eval_case")
    op.drop_table("eval_case")
