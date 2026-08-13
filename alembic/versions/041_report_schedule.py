"""report_schedule: 定时报告调度记录 + 种入一条停用的月度经营报告模板（docs/25 P1-1）

Revision ID: 041_report_schedule
Revises: 040_workflow_run_engine
Create Date: 2026-08-13

加法式：新增 report_schedule 表。种一条 enabled=false / creator_id=NULL 的月报模板——管理员置
负责人并启用方激活；配合 report_scheduler_enabled 开关（默认关）三重保险，未激活前生产逐字不变。
系统发起走 plan_work → start_workflow 同一 is_red_line 入口，对外步骤前必停 waiting_human。
"""
import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "041_report_schedule"
down_revision: str | None = "040_workflow_run_engine"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_REQUEST = (
    "汇总本月各部门经营数据，对比公司知识库中的历史数据，清洗校验后生成一份标准化的月度经营报告"
    "初稿（含关键指标、趋势、问题与建议），推送运营负责人审核；审核通过后再将报告留存到公司知识库。"
)


def upgrade() -> None:
    op.create_table(
        "report_schedule",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("create_time", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("update_time", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_delete", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("request_text", sa.Text(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("creator_id", sa.Uuid(), sa.ForeignKey("sys_user.id"), nullable=True),
        sa.Column(
            "assignee_agent_id", sa.Uuid(), sa.ForeignKey("agent_role.id"), nullable=True
        ),
        sa.Column("day_of_month", sa.Integer(), nullable=False),
        sa.Column("hour", sa.Integer(), nullable=False, server_default="9"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("last_fired_period", sa.String(7), nullable=True),
        sa.CheckConstraint("day_of_month BETWEEN 1 AND 31", name="ck_report_schedule_day"),
        sa.CheckConstraint("hour BETWEEN 0 AND 23", name="ck_report_schedule_hour"),
    )
    op.execute(
        sa.text(
            "INSERT INTO report_schedule "
            "(id, is_delete, name, request_text, title, day_of_month, hour, enabled, "
            "create_time, update_time) VALUES "
            "(:id, false, :name, :request_text, :title, 1, 9, false, now(), now())"
        ).bindparams(
            id=uuid.uuid4(),
            name="月度经营报告",
            request_text=_REQUEST,
            title="月度经营报告",
        )
    )


def downgrade() -> None:
    op.drop_table("report_schedule")
