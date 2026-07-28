"""任务卡表（docs/03 §3.3，阶段3）：任务主表 + 流转日志。"""

import uuid
from typing import Any

from sqlalchemy import JSON, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.contexts.business.task_management.domain.state_machine import CREATED
from app.platform.database.model import Base, CommonMixin

_JSONB = JSON().with_variant(JSONB(), "postgresql")


class TaskCard(CommonMixin, Base):
    """任务卡主表。assignee_agent_id 指向执行的智能体角色（真人接收后续扩展）。"""

    __tablename__ = "task_card"

    title: Mapped[str] = mapped_column(String(200))
    task_type: Mapped[str] = mapped_column(String(32))
    priority: Mapped[str] = mapped_column(String(16), default="normal", server_default="normal")
    status: Mapped[str] = mapped_column(String(24), default=CREATED, server_default=CREATED)
    creator_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sys_user.id"))
    assignee_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_role.id"), nullable=True
    )
    # F4a 归属/分派/风险（纯加列，历史行取默认）
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sys_department.id"), nullable=True
    )
    risk_level: Mapped[str] = mapped_column(String(16), default="low", server_default="low")
    assignee_type: Mapped[str] = mapped_column(
        String(16), default="agent", server_default="agent"
    )  # agent（AI 执行）/ user（派真人，scheduler 跳过）
    assignee_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    origin_type: Mapped[str | None] = mapped_column(
        String(16), nullable=True
    )  # proposal/meeting/manual/discussion
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("task_card.id"), nullable=True
    )  # 拆解出的子任务指向父任务
    # 任务编排（docs/14 阶段B）：父卡下的 DAG 步骤（纯加列，历史行取默认，不破坏现有卡）
    step_no: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 步骤序号（0=首步）
    depends_on: Mapped[list[str]] = mapped_column(
        _JSONB, default=list, server_default="[]"
    )  # 依赖的前序步骤卡 id 列表（DAG，空=无依赖可立即执行）
    step_input: Mapped[dict[str, Any]] = mapped_column(
        _JSONB, default=dict, server_default="{}"
    )  # 被依赖步骤的产出注入（datasets/artifacts 引用）
    sla_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(_JSONB, default=dict)
    result_content: Mapped[str | None] = mapped_column(Text, nullable=True)


class TaskCardLog(CommonMixin, Base):
    """任务流转日志（每次状态变更一行）。"""

    __tablename__ = "task_card_log"

    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("task_card.id"))
    from_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    to_status: Mapped[str] = mapped_column(String(24))
    # 操作者松引用（真人 sys_user 或智能体 agent_role，不加 FK）
    operator_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
