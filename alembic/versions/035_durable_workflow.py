"""durable Agent workflow runtime tables and trace linkage

Revision ID: 035_durable_workflow
Revises: 034_merge_feishu_oauth
Create Date: 2026-07-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "035_durable_workflow"
down_revision: str | None = "034_merge_feishu_oauth"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _common_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("create_time", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("update_time", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_delete", sa.Boolean(), nullable=False, server_default="false"),
    ]


def upgrade() -> None:
    op.create_table(
        "workflow_run",
        *_common_columns(),
        sa.Column("parent_task_id", sa.Uuid(), sa.ForeignKey("task_card.id"), nullable=True),
        sa.Column("creator_id", sa.Uuid(), sa.ForeignKey("sys_user.id"), nullable=False),
        sa.Column("assignee_agent_id", sa.Uuid(), sa.ForeignKey("agent_role.id"), nullable=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("request_text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="queued"),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("plan", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_msg", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_workflow_run_status_time", "workflow_run", ["status", "update_time"])
    op.create_index("uq_workflow_run_trace", "workflow_run", ["trace_id"], unique=True)

    op.create_table(
        "workflow_step",
        *_common_columns(),
        sa.Column("workflow_run_id", sa.Uuid(), sa.ForeignKey("workflow_run.id"), nullable=False),
        sa.Column("task_card_id", sa.Uuid(), sa.ForeignKey("task_card.id"), nullable=True),
        sa.Column("assignee_agent_id", sa.Uuid(), sa.ForeignKey("agent_role.id"), nullable=True),
        sa.Column("step_no", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("skill", sa.String(64), nullable=False),
        sa.Column("instruction", sa.Text(), nullable=False),
        sa.Column("red_line", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("status", sa.String(24), nullable=False, server_default="queued"),
        sa.Column("depends_on", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("input_data", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("output_data", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_owner", sa.String(128), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "uq_workflow_step_no", "workflow_step", ["workflow_run_id", "step_no"], unique=True
    )
    op.create_index(
        "ix_workflow_step_ready", "workflow_step", ["workflow_run_id", "status", "lease_until"]
    )
    op.create_index("ix_workflow_step_task", "workflow_step", ["task_card_id"], unique=True)

    op.create_table(
        "workflow_event",
        *_common_columns(),
        sa.Column("workflow_run_id", sa.Uuid(), sa.ForeignKey("workflow_run.id"), nullable=False),
        sa.Column("workflow_step_id", sa.Uuid(), sa.ForeignKey("workflow_step.id"), nullable=True),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=True),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default="{}"),
    )
    op.create_index(
        "ix_workflow_event_run_time", "workflow_event", ["workflow_run_id", "create_time"]
    )

    op.create_table(
        "outbox_event",
        *_common_columns(),
        sa.Column("aggregate_type", sa.String(32), nullable=False),
        sa.Column("aggregate_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("dedupe_key", sa.String(255), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_owner", sa.String(128), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
    )
    op.create_index("uq_outbox_dedupe", "outbox_event", ["dedupe_key"], unique=True)
    op.create_index("ix_outbox_poll", "outbox_event", ["status", "available_at", "lease_until"])

    op.create_table(
        "tool_execution",
        *_common_columns(),
        sa.Column("workflow_run_id", sa.Uuid(), sa.ForeignKey("workflow_run.id"), nullable=True),
        sa.Column("workflow_step_id", sa.Uuid(), sa.ForeignKey("workflow_step.id"), nullable=True),
        sa.Column(
            "agent_task_record_id", sa.Uuid(), sa.ForeignKey("agent_task_record.id"), nullable=True
        ),
        sa.Column("trace_id", sa.Uuid(), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tool_key", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("request_data", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("result_data", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("error_msg", sa.Text(), nullable=True),
    )
    op.create_index("uq_tool_execution_key", "tool_execution", ["idempotency_key"], unique=True)
    op.create_index("ix_tool_execution_step", "tool_execution", ["workflow_step_id", "tool_key"])

    for table in ("agent_task_record", "llm_call_log"):
        op.add_column(table, sa.Column("workflow_run_id", sa.Uuid(), nullable=True))
        op.add_column(table, sa.Column("workflow_step_id", sa.Uuid(), nullable=True))
        op.add_column(table, sa.Column("attempt_no", sa.Integer(), nullable=True))
        op.add_column(table, sa.Column("trace_id", sa.Uuid(), nullable=True))
        op.create_foreign_key(
            f"fk_{table}_workflow_run", table, "workflow_run", ["workflow_run_id"], ["id"]
        )
        op.create_foreign_key(
            f"fk_{table}_workflow_step", table, "workflow_step", ["workflow_step_id"], ["id"]
        )

    op.add_column("deliverable", sa.Column("idempotency_key", sa.String(255), nullable=True))
    op.create_index("uq_deliverable_idempotency", "deliverable", ["idempotency_key"], unique=True)
    op.add_column("collab_request", sa.Column("idempotency_key", sa.String(255), nullable=True))
    op.create_index("uq_collab_req_idempotency", "collab_request", ["idempotency_key"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_collab_req_idempotency", table_name="collab_request")
    op.drop_column("collab_request", "idempotency_key")
    op.drop_index("uq_deliverable_idempotency", table_name="deliverable")
    op.drop_column("deliverable", "idempotency_key")
    for table in ("llm_call_log", "agent_task_record"):
        op.drop_constraint(f"fk_{table}_workflow_step", table, type_="foreignkey")
        op.drop_constraint(f"fk_{table}_workflow_run", table, type_="foreignkey")
        op.drop_column(table, "trace_id")
        op.drop_column(table, "attempt_no")
        op.drop_column(table, "workflow_step_id")
        op.drop_column(table, "workflow_run_id")
    op.drop_table("tool_execution")
    op.drop_table("outbox_event")
    op.drop_table("workflow_event")
    op.drop_table("workflow_step")
    op.drop_table("workflow_run")
