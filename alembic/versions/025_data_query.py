"""data query skill: seed agent_data_query 开关

Revision ID: 025_data_query
Revises: 024_td_event_alias
Create Date: 2026-07-17

取数技能（阶段3）:AI 用【取数】<只读SQL>查运营数据，护栏校验+审计。
seed 总开关 agent_data_query=true（关掉则不注入提示词段、不执行取数指令）。
"""
import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "025_data_query"
down_revision: str | None = "024_td_event_alias"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONFIG_KEY = "agent_data_query"


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
