"""持久化 Agent 工作流运行时模型。

工作流执行状态与人机界面 TaskCard 分离；TaskCard 仅作为兼容镜像。Outbox、租约和
ToolExecution 共同提供多 worker 抢占、崩溃恢复和副作用幂等地基。
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CommonMixin
from app.platform.outbox.model import (
    OUTBOX_DONE as OUTBOX_DONE,
)
from app.platform.outbox.model import (
    OUTBOX_FAILED as OUTBOX_FAILED,
)
from app.platform.outbox.model import (
    OUTBOX_PENDING as OUTBOX_PENDING,
)
from app.platform.outbox.model import (
    OUTBOX_PROCESSING as OUTBOX_PROCESSING,
)
from app.platform.outbox.model import (
    OutboxEvent as OutboxEvent,
)

_JSONB = JSON().with_variant(JSONB(), "postgresql")

RUN_QUEUED = "queued"
RUN_RUNNING = "running"
RUN_WAITING_HUMAN = "waiting_human"
RUN_SUCCEEDED = "succeeded"
RUN_FAILED = "failed"
RUN_CANCELLED = "cancelled"

STEP_QUEUED = "queued"
STEP_RUNNING = "running"
STEP_WAITING_HUMAN = "waiting_human"
STEP_SUCCEEDED = "succeeded"
STEP_FAILED = "failed"
STEP_CANCELLED = "cancelled"

TOOL_PENDING = "pending"
TOOL_RUNNING = "running"
TOOL_SUCCEEDED = "succeeded"
TOOL_FAILED = "failed"


class WorkflowRun(CommonMixin, Base):
    """一个持久化编排实例；状态是执行真相源，TaskCard 仅用于展示与真人操作。"""

    __tablename__ = "workflow_run"
    __table_args__ = (
        Index("ix_workflow_run_status_time", "status", "update_time"),
        Index("uq_workflow_run_trace", "trace_id", unique=True),
    )

    parent_task_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("task_card.id"), nullable=True
    )
    creator_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sys_user.id"))
    assignee_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_role.id"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(200))
    request_text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default=RUN_QUEUED, server_default=RUN_QUEUED)
    trace_id: Mapped[uuid.UUID] = mapped_column(Uuid, default=uuid.uuid4)
    plan: Mapped[list[dict[str, Any]]] = mapped_column(_JSONB, default=list, server_default="[]")
    version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # 创建期固定的执行引擎（docs/24 §4）：新建时读 config.workflow_engine 盖戳、之后不可改写——
    # 避免双真源（docs/21 §14），并支撑按引擎 drain（count_active_runs_by_engine）。
    engine: Mapped[str] = mapped_column(String(32), default="database", server_default="database")
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WorkflowStep(CommonMixin, Base):
    """工作流步骤；通过租约和 version 条件更新保证单一有效执行者。"""

    __tablename__ = "workflow_step"
    __table_args__ = (
        Index("uq_workflow_step_no", "workflow_run_id", "step_no", unique=True),
        Index("ix_workflow_step_ready", "workflow_run_id", "status", "lease_until"),
        Index("ix_workflow_step_task", "task_card_id", unique=True),
    )

    workflow_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflow_run.id"))
    task_card_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("task_card.id"), nullable=True
    )
    assignee_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_role.id"), nullable=True
    )
    step_no: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200))
    skill: Mapped[str] = mapped_column(String(64))
    instruction: Mapped[str] = mapped_column(Text)
    red_line: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    status: Mapped[str] = mapped_column(
        String(24), default=STEP_QUEUED, server_default=STEP_QUEUED
    )
    depends_on: Mapped[list[str]] = mapped_column(_JSONB, default=list, server_default="[]")
    input_data: Mapped[dict[str, Any]] = mapped_column(_JSONB, default=dict, server_default="{}")
    output_data: Mapped[dict[str, Any]] = mapped_column(_JSONB, default=dict, server_default="{}")
    attempt: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    lease_owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WorkflowEvent(CommonMixin, Base):
    """追加式工作流事件，供追踪、恢复审计和未来 LangGraph adapter 消费。"""

    __tablename__ = "workflow_event"
    __table_args__ = (Index("ix_workflow_event_run_time", "workflow_run_id", "create_time"),)

    workflow_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflow_run.id"))
    workflow_step_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workflow_step.id"), nullable=True
    )
    event_type: Mapped[str] = mapped_column(String(64))
    attempt: Mapped[int | None] = mapped_column(Integer, nullable=True)
    trace_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    payload: Mapped[dict[str, Any]] = mapped_column(_JSONB, default=dict, server_default="{}")


class ToolExecution(CommonMixin, Base):
    """一次强类型技能执行；唯一幂等键把重复事件收敛为同一结果。"""

    __tablename__ = "tool_execution"
    __table_args__ = (
        Index("uq_tool_execution_key", "idempotency_key", unique=True),
        Index("ix_tool_execution_step", "workflow_step_id", "tool_key"),
    )

    workflow_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workflow_run.id"), nullable=True
    )
    workflow_step_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workflow_step.id"), nullable=True
    )
    agent_task_record_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_task_record.id"), nullable=True
    )
    trace_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    attempt: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    tool_key: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(
        String(16), default=TOOL_PENDING, server_default=TOOL_PENDING
    )
    request_data: Mapped[dict[str, Any]] = mapped_column(_JSONB, default=dict, server_default="{}")
    result_data: Mapped[dict[str, Any]] = mapped_column(_JSONB, default=dict, server_default="{}")
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)
