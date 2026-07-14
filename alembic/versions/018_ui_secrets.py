"""sys_config 加 is_secret + 种 AI/飞书/外部数据 可 UI 填写的配置项

Revision ID: 018_ui_secrets
Revises: 017_td_config
Create Date: 2026-07-14

红线调整（用户确认）：密钥可在 UI 填写。密钥存 sys_config(is_secret=true)，
list 读时脱敏、审计打码、绝不硬编码；app 经 runtime_config 覆盖 .env 使用。
种子值留空 → 未填时回退 .env（现有 .env 密钥继续生效，平滑迁移）。
"""
import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "018_ui_secrets"
down_revision: str | None = "017_td_config"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (key, category, is_secret)
_SEEDS = [
    ("deepseek_api_key", "llm", True),
    ("dashscope_api_key", "llm", True),      # 通义/Qwen（也供 embedding 兜底）
    ("zhipu_api_key", "llm", True),          # GLM
    ("anthropic_api_key", "llm", True),
    ("embedding_base_url", "embedding", False),
    ("embedding_model", "embedding", False),
    ("embedding_api_key", "embedding", True),
    ("feishu_app_id", "feishu", False),
    ("feishu_app_secret", "feishu", True),
    ("feishu_notify_enabled", "feishu", False),  # "true"/"false"
    ("feishu_ops_chat_id", "feishu", False),
    ("td_api_secret", "dataif", True),
]
_KEYS = tuple(k for k, _c, _s in _SEEDS)


def upgrade() -> None:
    op.add_column(
        "sys_config",
        sa.Column("is_secret", sa.Boolean(), nullable=False, server_default="false"),
    )
    for key, category, is_secret in _SEEDS:
        op.execute(
            sa.text(
                "INSERT INTO sys_config "
                "(id, key, value, value_type, category, is_editable, is_secret, is_delete, "
                "create_time, update_time) VALUES "
                "(:id, :key, to_jsonb(CAST('' AS text)), 'string', :cat, true, :sec, false, "
                "now(), now())"
            ).bindparams(id=uuid.uuid4(), key=key, cat=category, sec=is_secret)
        )


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM sys_config WHERE key IN :keys").bindparams(
            sa.bindparam("keys", value=_KEYS, expanding=True)
        )
    )
    op.drop_column("sys_config", "is_secret")
