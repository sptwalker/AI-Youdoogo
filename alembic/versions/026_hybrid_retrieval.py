"""hybrid retrieval: pg_trgm 扩展 + chunk_text 三元组 GIN 索引 + seed 混合检索开关

Revision ID: 026_hybrid_retrieval
Revises: 025_data_query
Create Date: 2026-07-17

混合检索阶段A.1（docs/15）:向量臂之外加 pg_trgm 关键词臂做精确/专名/型号匹配。
- CREATE EXTENSION pg_trgm（contrib 自带，免改镜像）。
- knowledge_vector.chunk_text 建 GIN(gin_trgm_ops) 三元组索引，加速关键词臂相似度过滤。
- seed retrieval_hybrid_enabled=true（关掉则 search() 退回纯向量，优雅降级）。
"""
import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "026_hybrid_retrieval"
down_revision: str | None = "025_data_query"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONFIG_KEY = "retrieval_hybrid_enabled"
_INDEX = "ix_kv_chunk_trgm"


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        f"CREATE INDEX IF NOT EXISTS {_INDEX} ON knowledge_vector "
        "USING gin (chunk_text gin_trgm_ops)"
    )
    op.execute(
        sa.text(
            "INSERT INTO sys_config "
            "(id, key, value, value_type, category, is_editable, is_secret, is_delete, "
            "create_time, update_time) VALUES "
            "(:id, :key, to_jsonb(true), 'bool', 'feature', true, false, false, now(), now())"
        ).bindparams(id=uuid.uuid4(), key=_CONFIG_KEY)
    )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM sys_config WHERE key = :key").bindparams(key=_CONFIG_KEY))
    op.execute(f"DROP INDEX IF EXISTS {_INDEX}")
    # pg_trgm 扩展保留：可能被其他对象依赖，删除风险大于收益
