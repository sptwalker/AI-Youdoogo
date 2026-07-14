"""desktop chat: agent_role.owner_user_id + desktop_message 表 + seed 桌面配置

Revision ID: 020_desktop_chat
Revises: 019_ai_provider
Create Date: 2026-07-14

专属AI助理 + 工作桌面持久对话：
- agent_role 加 owner_user_id（非空=某真人专属助理，不进组织树/智能体列表）。
- desktop_message：每个真人一条连续消息流，桌面展示最近 N 天，更早归档进助理 personal KB 后硬删。
- seed 两项非密配置：desktop_history_days=10 / desktop_roundtable_rounds=2。
"""
import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "020_desktop_chat"
down_revision: str | None = "019_ai_provider"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONFIG_SEEDS = [("desktop_history_days", "10"), ("desktop_roundtable_rounds", "2")]


def _common_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("create_time", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("update_time", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_delete", sa.Boolean(), server_default="false", nullable=False),
    ]


def upgrade() -> None:
    op.add_column(
        "agent_role",
        sa.Column(
            "owner_user_id", sa.Uuid(), sa.ForeignKey("sys_user.id"), nullable=True
        ),
    )
    op.create_index("ix_agent_owner_user", "agent_role", ["owner_user_id"])

    op.create_table(
        "desktop_message",
        *_common_columns(),
        sa.Column("owner_user_id", sa.Uuid(), sa.ForeignKey("sys_user.id"), nullable=False),
        sa.Column("speaker_type", sa.String(8), nullable=False),
        sa.Column(
            "speaker_agent_id", sa.Uuid(), sa.ForeignKey("agent_role.id"), nullable=True
        ),
        sa.Column("speaker_name", sa.String(64), nullable=False, server_default=""),
        sa.Column("content", sa.Text(), nullable=False),
    )
    op.create_index(
        "ix_desktop_msg_owner_time", "desktop_message", ["owner_user_id", "create_time"]
    )

    for key, value in _CONFIG_SEEDS:
        op.execute(
            sa.text(
                "INSERT INTO sys_config "
                "(id, key, value, value_type, category, is_editable, is_secret, is_delete, "
                "create_time, update_time) VALUES "
                "(:id, :key, to_jsonb(CAST(:val AS integer)), 'int', 'feature', true, false, "
                "false, now(), now())"
            ).bindparams(id=uuid.uuid4(), key=key, val=value)
        )


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM sys_config WHERE key IN :keys").bindparams(
            sa.bindparam("keys", value=tuple(k for k, _ in _CONFIG_SEEDS), expanding=True)
        )
    )
    op.drop_index("ix_desktop_msg_owner_time", table_name="desktop_message")
    op.drop_table("desktop_message")
    op.drop_index("ix_agent_owner_user", table_name="agent_role")
    op.drop_column("agent_role", "owner_user_id")
