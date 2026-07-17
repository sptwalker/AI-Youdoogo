"""deliverable: 建交付物表 + seed agent_deliver 开关

Revision ID: 023_deliverable
Revises: 022_collab_protocol
Create Date: 2026-07-15

智能体文件交付（docs/13 §11 交付技能）：
- 建 deliverable 表：AI 产出落 MinIO 后交付到真人桌面「文件交付区」的一行记录。
- seed 总开关 agent_deliver=true（关掉则不注入提示词段、不执行交付指令）。
"""
import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "023_deliverable"
down_revision: str | None = "022_collab_protocol"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONFIG_KEY = "agent_deliver"


def upgrade() -> None:
    op.create_table(
        "deliverable",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("owner_user_id", sa.Uuid(), sa.ForeignKey("sys_user.id"), nullable=False),
        sa.Column("agent_id", sa.Uuid(), sa.ForeignKey("agent_role.id"), nullable=True),
        sa.Column("agent_name", sa.String(64), server_default="", nullable=False),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("file_format", sa.String(8), nullable=False),
        sa.Column("storage_path", sa.String(512), nullable=False),
        sa.Column("file_size", sa.Integer(), server_default="0", nullable=False),
        sa.Column("create_time", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("update_time", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_delete", sa.Boolean(), server_default="false", nullable=False),
    )
    op.create_index(
        "ix_deliverable_owner_time", "deliverable", ["owner_user_id", "create_time"]
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
    op.drop_index("ix_deliverable_owner_time", table_name="deliverable")
    op.drop_table("deliverable")
