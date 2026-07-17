"""rerank: seed retrieval_rerank_enabled 开关（默认关）

Revision ID: 027_rerank
Revises: 026_hybrid_retrieval
Create Date: 2026-07-17

混合检索 A.2（docs/15）:RRF 融合后 cross-encoder 精排。默认关（false）——
开启须先在系统配置填 rerank_base_url / rerank_api_key / rerank_model，否则精排优雅降级。
"""
import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "027_rerank"
down_revision: str | None = "026_hybrid_retrieval"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONFIG_KEY = "retrieval_rerank_enabled"


def upgrade() -> None:
    op.execute(
        sa.text(
            "INSERT INTO sys_config "
            "(id, key, value, value_type, category, is_editable, is_secret, is_delete, "
            "create_time, update_time) VALUES "
            "(:id, :key, to_jsonb(false), 'bool', 'feature', true, false, false, now(), now())"
        ).bindparams(id=uuid.uuid4(), key=_CONFIG_KEY)
    )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM sys_config WHERE key = :key").bindparams(key=_CONFIG_KEY))
