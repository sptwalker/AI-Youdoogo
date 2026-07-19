"""retrieval sources: agent_task_record 加 sources 列（检索引用溯源，H2.3）

Revision ID: 032_task_record_sources
Revises: 031_encrypt_api_key
Create Date: 2026-07-20

可靠性 P1（docs/16 H2.3）:AgentTaskRecord 加 sources JSONB——记录本次执行注入了哪些
知识库片段，让"某AI产出用了哪些资料"事后可精确重建。纯加列，历史行取默认 []。
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "032_task_record_sources"
down_revision: str | None = "031_encrypt_api_key"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_task_record",
        sa.Column("sources", postgresql.JSONB(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("agent_task_record", "sources")
