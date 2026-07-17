"""collab protocol: seed agent_collab_protocol 开关

Revision ID: 022_collab_protocol
Revises: 021_env_snapshot
Create Date: 2026-07-15

智能体协作原语（docs/13 §10）：AI 回复中可用【咨询 @AI名】/【发起协作】指令；
本迁移 seed 总开关 agent_collab_protocol=true（关掉则不注入提示词段、不执行指令）。
"""
import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "022_collab_protocol"
down_revision: str | None = "021_env_snapshot"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONFIG_KEY = "agent_collab_protocol"


def upgrade() -> None:
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
