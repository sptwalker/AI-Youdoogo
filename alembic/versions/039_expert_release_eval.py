"""expert_release 评测证据列：eval_score / eval_case_count（Phase 3 Module 3 / docs/23 §4.3）

Revision ID: 039_expert_release_eval
Revises: 038_expert_release
Create Date: 2026-07-31

加法式：给不可变发布快照附评测证据两列（可空）。评测只产分不自动发布，是否发布仍真人确认。
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "039_expert_release_eval"
down_revision: str | None = "038_expert_release"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("expert_release", sa.Column("eval_score", sa.Float(), nullable=True))
    op.add_column("expert_release", sa.Column("eval_case_count", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("expert_release", "eval_case_count")
    op.drop_column("expert_release", "eval_score")
