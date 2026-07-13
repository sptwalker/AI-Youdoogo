"""audit_log + sys_config + task/ops/llm 加归属列（docs/13 F4a）

Revision ID: 014_audit_config
Revises: 013_discussion
Create Date: 2026-07-13

审计留痕 + 可编辑配置基座 + 归属列（纯加列，历史行 NULL/默认）。
种子 sys_config('agent_global_prompt') 供提示词分层注入。
"""
import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "014_audit_config"
down_revision: str | None = "013_discussion"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ACTIVE = "is_delete = false"
_GLOBAL_PROMPT = (
    "【公司红线】你是创想悦动公司的 AI 顾问/助理，仅有建议、分析、辅助执行权；"
    "涉及资金、人事、项目、重大业务调整的决议必须由真人确认才生效，你的产出一律为草稿/参考。"
    "只依据已知事实作答、禁止编造；引用资料须可溯源；保持专业、简明的公司口吻。"
)


def _common_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("create_time", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("update_time", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_delete", sa.Boolean(), server_default="false", nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "audit_log",
        *_common_columns(),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("sys_user.id"), nullable=True),
        sa.Column("actor_role", sa.String(32), nullable=True),
        sa.Column("action", sa.String(48), nullable=False),
        sa.Column("target_type", sa.String(32), nullable=True),
        sa.Column("target_id", sa.Uuid(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("detail", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("ip", sa.String(64), nullable=True),
        sa.Column("result", sa.String(16), nullable=False, server_default="ok"),
    )
    op.create_index("ix_audit_action", "audit_log", ["action"])
    op.create_index("ix_audit_actor", "audit_log", ["actor_id"])
    op.create_index("ix_audit_target", "audit_log", ["target_type", "target_id"])

    op.create_table(
        "sys_config",
        *_common_columns(),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("value", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column("value_type", sa.String(16), nullable=False, server_default="string"),
        sa.Column("category", sa.String(32), nullable=False, server_default="feature"),
        sa.Column("is_editable", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
    )
    op.create_index("uq_config_key", "sys_config", ["key"], unique=True,
                    postgresql_where=sa.text(_ACTIVE))

    # 种子：全局红线提示词（提示词分层注入的可编辑前缀）
    op.execute(
        sa.text(
            "INSERT INTO sys_config "
            "(id, key, value, value_type, category, is_editable, is_delete, "
            "create_time, update_time) VALUES "
            "(:id, 'agent_global_prompt', to_jsonb(:val::text), 'text', 'prompt', true, false, "
            "now(), now())"
        ).bindparams(id=uuid.uuid4(), val=_GLOBAL_PROMPT)
    )

    # task_card 加归属/分派/风险列
    op.add_column("task_card", sa.Column("department_id", sa.Uuid(),
                  sa.ForeignKey("sys_department.id"), nullable=True))
    op.add_column("task_card", sa.Column("risk_level", sa.String(16),
                  nullable=False, server_default="low"))
    op.add_column("task_card", sa.Column("assignee_type", sa.String(16),
                  nullable=False, server_default="agent"))
    op.add_column("task_card", sa.Column("assignee_user_id", sa.Uuid(), nullable=True))
    op.add_column("task_card", sa.Column("origin_type", sa.String(16), nullable=True))

    # ops/llm 加 department_id（部门切片/预算归集）
    op.add_column("ops_daily_metric", sa.Column("department_id", sa.Uuid(),
                  sa.ForeignKey("sys_department.id"), nullable=True))
    op.add_column("llm_call_log", sa.Column("department_id", sa.Uuid(),
                  sa.ForeignKey("sys_department.id"), nullable=True))


def downgrade() -> None:
    op.drop_column("llm_call_log", "department_id")
    op.drop_column("ops_daily_metric", "department_id")
    for col in ("origin_type", "assignee_user_id", "assignee_type", "risk_level", "department_id"):
        op.drop_column("task_card", col)
    op.drop_index("uq_config_key", table_name="sys_config")
    op.drop_table("sys_config")
    op.drop_index("ix_audit_target", table_name="audit_log")
    op.drop_index("ix_audit_actor", table_name="audit_log")
    op.drop_index("ix_audit_action", table_name="audit_log")
    op.drop_table("audit_log")
