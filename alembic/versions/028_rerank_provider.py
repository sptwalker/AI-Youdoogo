"""rerank provider: seed rerank 端点/密钥/模型（默认 SiliconFlow bge-reranker-v2-m3）

Revision ID: 028_rerank_provider
Revises: 027_rerank
Create Date: 2026-07-17

混合检索 A.2（docs/15）:027 只种了 retrieval_rerank_enabled 开关，缺连接配置项——
本迁移补 rerank_base_url / rerank_model / rerank_api_key 三键（对齐 018 的 embedding 三件套）。
默认服务选定 SiliconFlow（OpenAI 兼容 /rerank 端点，与 app/knowledge/rerank.py 契约一致）:
    base_url = https://api.siliconflow.cn/v1   model = BAAI/bge-reranker-v2-m3
端点/模型预填好、密钥留空（is_secret，UI 填）。填密钥 + 开 retrieval_rerank_enabled 即生效;
密钥未填 → rerank 抛 RerankError → retrieval 优雅降级回 RRF 融合序，不阻断。
"""
import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "028_rerank_provider"
down_revision: str | None = "027_rerank"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (key, value, is_secret) —— 端点/模型预填 SiliconFlow 默认，密钥留空由 UI 填
_SEEDS = [
    ("rerank_base_url", "https://api.siliconflow.cn/v1", False),
    ("rerank_model", "BAAI/bge-reranker-v2-m3", False),
    ("rerank_api_key", "", True),
]
_KEYS = tuple(k for k, _v, _s in _SEEDS)


def upgrade() -> None:
    for key, value, is_secret in _SEEDS:
        op.execute(
            sa.text(
                "INSERT INTO sys_config "
                "(id, key, value, value_type, category, is_editable, is_secret, is_delete, "
                "create_time, update_time) VALUES "
                "(:id, :key, to_jsonb(CAST(:val AS text)), 'string', 'embedding', true, :sec, "
                "false, now(), now())"
            ).bindparams(id=uuid.uuid4(), key=key, val=value, sec=is_secret)
        )


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM sys_config WHERE key IN :keys").bindparams(
            sa.bindparam("keys", value=_KEYS, expanding=True)
        )
    )
