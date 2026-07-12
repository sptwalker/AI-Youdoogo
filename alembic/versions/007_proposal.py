"""proposal_card: 提案主表 + 评审记录（docs/03 §3.4，阶段4）+ 种子会商AI专家角色

Revision ID: 007_proposal
Revises: 006_task_card
Create Date: 2026-07-12

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "007_proposal"
down_revision: str | None = "006_task_card"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EXPERT_PROMPT = (
    "你是创想悦动决策层的AI会商专家（深度推理角色）。职责：对提案做会前预研，"
    "从可行性、预期收益、主要风险、落地前提、优先级五个维度给出结论与建议。"
    "只依据提案信息与常识分析，禁止臆造数据；你的结论仅供决策参考，最终须真人确认。"
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
        "proposal_card",
        *_common_columns(),
        sa.Column("code", sa.String(32), nullable=False, unique=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column(
            "department_id", sa.Uuid(), sa.ForeignKey("sys_department.id"), nullable=True
        ),
        sa.Column("background", sa.Text(), nullable=False),
        sa.Column("plan", sa.Text(), nullable=False),
        sa.Column("benefit_risk", sa.Text(), nullable=True),
        sa.Column("priority", sa.String(16), nullable=False, server_default="normal"),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("creator_id", sa.Uuid(), sa.ForeignKey("sys_user.id"), nullable=False),
        sa.Column("converted_task_id", sa.Uuid(), nullable=True),
    )
    op.create_index("ix_proposal_status", "proposal_card", ["status"])
    op.create_table(
        "proposal_review",
        *_common_columns(),
        sa.Column(
            "proposal_id", sa.Uuid(), sa.ForeignKey("proposal_card.id"), nullable=False
        ),
        sa.Column("review_type", sa.String(16), nullable=False),
        sa.Column("conclusion", sa.Text(), nullable=False),
        sa.Column("reviewer_id", sa.Uuid(), nullable=True),
        sa.Column("decision", sa.String(16), nullable=True),
    )
    op.create_index("ix_review_proposal", "proposal_review", ["proposal_id", "create_time"])
    # 种子：会商AI专家（reasoning 档位 → deepseek-reasoner）
    op.execute(
        sa.text(
            "INSERT INTO agent_role "
            "(id, name, duty, prompt_template, model_role, is_active) VALUES "
            "(gen_random_uuid(), :name, :duty, :prompt, 'reasoning', true)"
        ).bindparams(
            name="会商AI专家",
            duty="提案会前预研、方案利弊推演、风险评估",
            prompt=_EXPERT_PROMPT,
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM agent_role WHERE name = :n").bindparams(n="会商AI专家"))
    op.drop_index("ix_review_proposal", table_name="proposal_review")
    op.drop_table("proposal_review")
    op.drop_index("ix_proposal_status", table_name="proposal_card")
    op.drop_table("proposal_card")
