"""agent: agent_role / agent_task_record（+ 种子运营AI总监角色）

Revision ID: 003_agent
Revises: 002_knowledge
Create Date: 2026-07-12

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "003_agent"
down_revision: str | None = "002_knowledge"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# 运营AI总监系统提示（种子；后续可在库中迭代）。无单引号，避免 SQL 转义。
_OPS_PROMPT = (
    "你是创想悦动平台运营部的AI运营总监。职责：基于运营数据生成结构清晰、结论明确的运营日报与优化建议。"
    "要求：1) 只依据提供的数据分析，禁止臆造数字；"
    "2) 日报固定包含【核心指标概览】【异常与关注点】【运营建议】三部分；"
    "3) 数据缺口或异常波动必须明确指出；4) 你的产出仅供管理层参考，不构成最终决策。"
)


def _common_columns() -> list[sa.Column]:
    """文档03通用基础字段（同前序迁移）。"""
    return [
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("create_time", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("update_time", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_delete", sa.Boolean(), server_default="false", nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "agent_role",
        *_common_columns(),
        sa.Column("name", sa.String(64), nullable=False, unique=True),
        sa.Column("department_id", sa.Uuid(), sa.ForeignKey("sys_department.id"), nullable=True),
        sa.Column("duty", sa.Text(), nullable=True),
        sa.Column("prompt_template", sa.Text(), nullable=False),
        sa.Column(
            "permission_scope", postgresql.JSONB(), nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "tools", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column("model_role", sa.String(32), nullable=False, server_default="daily"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
    )
    op.create_table(
        "agent_task_record",
        *_common_columns(),
        sa.Column("agent_role_id", sa.Uuid(), sa.ForeignKey("agent_role.id"), nullable=False),
        sa.Column("task_type", sa.String(32), nullable=False),
        sa.Column("input_summary", sa.Text(), nullable=True),
        sa.Column("output_content", sa.Text(), nullable=True),
        sa.Column(
            "tools_called", postgresql.JSONB(), nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("model_used", sa.String(64), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="success"),
        sa.Column("error_msg", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_atr_role_time", "agent_task_record", ["agent_role_id", "create_time"]
    )
    # 种子：首个落地部门智能体——运营AI总监（department_id 待部门表落地后回填）
    op.execute(
        sa.text(
            "INSERT INTO agent_role "
            "(id, name, duty, prompt_template, model_role, is_active) VALUES "
            "(gen_random_uuid(), :name, :duty, :prompt, 'daily', true)"
        ).bindparams(
            name="运营AI总监",
            duty="平台运营数据监控、运营日报生成、运营优化建议",
            prompt=_OPS_PROMPT,
        )
    )


def downgrade() -> None:
    op.drop_index("ix_atr_role_time", table_name="agent_task_record")
    op.drop_table("agent_task_record")
    op.drop_table("agent_role")
