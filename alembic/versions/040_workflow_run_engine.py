"""workflow_run 执行引擎溯源列：engine（docs/24 §4.2 / docs/21 Phase4 step6+7）

Revision ID: 040_workflow_run_engine
Revises: 039_expert_release_eval
Create Date: 2026-08-02

加法式：给 workflow_run 附创建期固定的执行引擎戳（非空，server_default=database，回填存量）。
支撑创建期固定引擎（避免双真源，docs/21 §14）与按引擎 drain（count_active_runs_by_engine）。
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "040_workflow_run_engine"
down_revision: str | None = "039_expert_release_eval"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workflow_run",
        sa.Column("engine", sa.String(32), nullable=False, server_default="database"),
    )


def downgrade() -> None:
    op.drop_column("workflow_run", "engine")
