"""050: 时间管理三表（docs/27 阶段 B2）——日程 / 专注番茄钟 / 时间记录，归 time_management Context。

个人数据行级隔离按 owner_id（docs/16 P0 / docs/27 §四）：owner_id 索引服务「我的当日/当周视图」。
红线：schedule.status=suggested 为智能排程建议态，真人 confirm 才置 confirmed。
linked_task_id/ref_task_id 为软引用（不建 FK，避免跨 Context 表耦合）。
"""

import sqlalchemy as sa

from alembic import op

revision: str = "050_time_management"
down_revision: str | None = "049_knowledge_base_owner"
branch_labels = None
depends_on = None


def _common_columns() -> list[sa.Column]:
    """CommonMixin 四列：id/create_time/update_time/is_delete（软删）。"""
    return [
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("create_time", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("update_time", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_delete", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    ]


def upgrade() -> None:
    op.create_table(
        "schedule",
        *_common_columns(),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("sys_user.id"), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False, server_default="manual"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="confirmed"),
        sa.Column("linked_task_id", sa.Uuid(), nullable=True),
    )
    op.create_index("ix_schedule_owner_start", "schedule", ["owner_id", "start_at"])

    op.create_table(
        "focus_session",
        *_common_columns(),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("sys_user.id"), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("planned_minutes", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column(
            "intercept_notifications",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_focus_session_owner_status", "focus_session", ["owner_id", "status"])

    op.create_table(
        "time_log",
        *_common_columns(),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("sys_user.id"), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("minutes", sa.Integer(), nullable=False),
        sa.Column("logged_date", sa.Date(), nullable=False),
        sa.Column("ref_task_id", sa.Uuid(), nullable=True),
    )
    op.create_index("ix_time_log_owner_date", "time_log", ["owner_id", "logged_date"])


def downgrade() -> None:
    op.drop_index("ix_time_log_owner_date", table_name="time_log")
    op.drop_table("time_log")
    op.drop_index("ix_focus_session_owner_status", table_name="focus_session")
    op.drop_table("focus_session")
    op.drop_index("ix_schedule_owner_start", table_name="schedule")
    op.drop_table("schedule")
