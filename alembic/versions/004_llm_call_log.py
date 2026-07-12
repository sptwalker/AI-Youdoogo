"""llm_call_log: LLM 用量记录表（docs/09 §5）

Revision ID: 004_llm_call_log
Revises: 003_agent
Create Date: 2026-07-12

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "004_llm_call_log"
down_revision: str | None = "003_agent"
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
        "llm_call_log",
        *_common_columns(),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("model", sa.String(64), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="success"),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("task_id", sa.Uuid(), nullable=True),
    )
    op.create_index("ix_llm_log_time", "llm_call_log", ["create_time"])


def downgrade() -> None:
    op.drop_index("ix_llm_log_time", table_name="llm_call_log")
    op.drop_table("llm_call_log")
