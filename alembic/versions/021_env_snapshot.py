"""env snapshot: data_source.owner_agent_id + seed agent_env_context 开关

Revision ID: 021_env_snapshot
Revises: 020_desktop_chat
Create Date: 2026-07-14

环境快照与系统档案员（docs/13 §9）：
- data_source 加 owner_agent_id（对接该数据接口的 AI 员工，快照展示用）。
- seed 非密配置 agent_env_context=true：是否向所有智能体提示词注入环境快照。
"""
import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "021_env_snapshot"
down_revision: str | None = "020_desktop_chat"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONFIG_KEY = "agent_env_context"


def upgrade() -> None:
    op.add_column(
        "data_source",
        sa.Column("owner_agent_id", sa.Uuid(), sa.ForeignKey("agent_role.id"), nullable=True),
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
    op.drop_column("data_source", "owner_agent_id")
