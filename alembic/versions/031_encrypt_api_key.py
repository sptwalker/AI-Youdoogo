"""encrypt secrets: ai_provider.api_key 列加宽 + 存量明文就地加密（H1.1）

Revision ID: 031_encrypt_api_key
Revises: 030_task_orchestration
Create Date: 2026-07-20

生产硬化 P0-1（docs/16）:AI 卡片 api_key 由明文改透明加密存储。
- 列 String(512) → String(1024)（密文更长）。
- 存量明文逐行加密（带 enc:v1: 前缀）;已加密行跳过（幂等）。
- 用 app.core.crypto.encrypt（Fernet，密钥由 APP_SECRET_KEY/JWT_SECRET 派生）。
回滚 downgrade 解密回明文（便于换密钥/排障），列宽保留 1024 无害。
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "031_encrypt_api_key"
down_revision: str | None = "030_task_orchestration"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from app.core.crypto import encrypt, is_encrypted

    op.alter_column("ai_provider", "api_key", type_=sa.String(1024))
    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT id, api_key FROM ai_provider WHERE api_key <> ''")
    ).fetchall()
    for row_id, key in rows:
        if key and not is_encrypted(key):
            bind.execute(
                sa.text("UPDATE ai_provider SET api_key = :k WHERE id = :id")
                .bindparams(k=encrypt(key), id=row_id)
            )


def downgrade() -> None:
    from app.core.crypto import decrypt, is_encrypted

    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT id, api_key FROM ai_provider WHERE api_key <> ''")
    ).fetchall()
    for row_id, key in rows:
        if key and is_encrypted(key):
            bind.execute(
                sa.text("UPDATE ai_provider SET api_key = :k WHERE id = :id")
                .bindparams(k=decrypt(key), id=row_id)
            )
    op.alter_column("ai_provider", "api_key", type_=sa.String(512))
