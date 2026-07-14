"""ai_provider: AI 模型卡片表 + 删 018 的 llm 类密钥种子（改走卡片）

Revision ID: 019_ai_provider
Revises: 018_ui_secrets
Create Date: 2026-07-14

卡片化多 Provider：AI 密钥从固定预置项（sys_config 的 deepseek/dashscope/zhipu/anthropic
_api_key）改为动态卡片（ai_provider 表）。必须建卡片才能用 AI，不回退 .env。
embedding/飞书/TD 密钥保留（那些不是 AI 模型卡片）。
"""
import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "019_ai_provider"
down_revision: str | None = "018_ui_secrets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# 018 种下、现改走卡片的 llm 类密钥项（升级删除；降级恢复）
_LLM_SECRET_KEYS = ("deepseek_api_key", "dashscope_api_key", "zhipu_api_key", "anthropic_api_key")


def _common_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("create_time", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("update_time", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_delete", sa.Boolean(), server_default="false", nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "ai_provider",
        *_common_columns(),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("tier", sa.String(16), nullable=False, server_default="daily"),
        sa.Column("base_url", sa.String(512), nullable=False),
        sa.Column("api_key", sa.String(512), nullable=False, server_default=""),
        sa.Column("api_key_hint", sa.String(16), nullable=False, server_default=""),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("last_test_status", sa.String(16), nullable=False, server_default="untested"),
        sa.Column("last_test_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_test_latency_ms", sa.Integer(), nullable=True),
        sa.Column("last_test_msg", sa.String(256), nullable=True),
    )
    op.create_index("ix_ai_provider_tier_active", "ai_provider", ["tier", "is_active"])

    # 删 018 的 llm 密钥项（改走卡片；embedding/feishu/td 保留）
    op.execute(
        sa.text("DELETE FROM sys_config WHERE key IN :keys").bindparams(
            sa.bindparam("keys", value=_LLM_SECRET_KEYS, expanding=True)
        )
    )


def downgrade() -> None:
    op.drop_index("ix_ai_provider_tier_active", table_name="ai_provider")
    op.drop_table("ai_provider")
    # 恢复 018 的 llm 密钥项（空值 secret，回退到卡片化之前）
    for key in _LLM_SECRET_KEYS:
        op.execute(
            sa.text(
                "INSERT INTO sys_config "
                "(id, key, value, value_type, category, is_editable, is_secret, is_delete, "
                "create_time, update_time) VALUES "
                "(:id, :key, to_jsonb(CAST('' AS text)), 'string', 'llm', true, true, false, "
                "now(), now())"
            ).bindparams(id=uuid.uuid4(), key=key)
        )
