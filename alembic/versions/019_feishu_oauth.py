"""飞书 OAuth：用户 open_id 绑定 + 非密登录配置

Revision ID: 019_feishu_oauth
Revises: 018_ui_secrets
Create Date: 2026-07-16
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "019_feishu_oauth"
down_revision: str | None = "018_ui_secrets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONFIG_KEYS = ("feishu_oauth_enabled", "feishu_redirect_url")


def upgrade() -> None:
    op.add_column("sys_user", sa.Column("feishu_open_id", sa.String(128), nullable=True))
    op.create_index(
        "uq_user_feishu_open_id",
        "sys_user",
        ["feishu_open_id"],
        unique=True,
        postgresql_where=sa.text("feishu_open_id IS NOT NULL"),
    )
    op.execute(
        sa.text(
            "INSERT INTO sys_config "
            "(id, key, value, value_type, category, is_editable, is_secret, is_delete, "
            "create_time, update_time) VALUES "
            "(:id, 'feishu_oauth_enabled', to_jsonb(CAST('' AS text)), 'bool', "
            "'feishu', true, false, false, now(), now())"
        ).bindparams(id=uuid.uuid4())
    )
    op.execute(
        sa.text(
            "INSERT INTO sys_config "
            "(id, key, value, value_type, category, is_editable, is_secret, is_delete, "
            "create_time, update_time) VALUES "
            "(:id, 'feishu_redirect_url', to_jsonb(CAST('' AS text)), 'string', "
            "'feishu', true, false, false, now(), now())"
        ).bindparams(id=uuid.uuid4())
    )


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM sys_config WHERE key IN :keys").bindparams(
            sa.bindparam("keys", value=_CONFIG_KEYS, expanding=True)
        )
    )
    op.drop_index("uq_user_feishu_open_id", table_name="sys_user")
    op.drop_column("sys_user", "feishu_open_id")
