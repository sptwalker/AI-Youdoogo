"""智能体表：角色配置 + 执行留痕（docs/03 §3.2，阶段1~2）。

agent_task_record 是「所有AI操作必须留痕、数据可溯源」红线的落地表（docs/04 §1）。
"""

import uuid
from typing import Any

from sqlalchemy import JSON, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CommonMixin

# JSONB 主类型；sqlite 单测下降级为通用 JSON，仅为 metadata.create_all 可跑
_JSONB = JSON().with_variant(JSONB(), "postgresql")


class AgentRole(CommonMixin, Base):
    """智能体角色配置表。model_role: daily→deepseek-chat / reasoning→deepseek-reasoner。"""

    __tablename__ = "agent_role"

    name: Mapped[str] = mapped_column(String(64), unique=True)
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sys_department.id"), nullable=True
    )
    duty: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_template: Mapped[str] = mapped_column(Text)
    permission_scope: Mapped[dict[str, Any]] = mapped_column(_JSONB, default=dict)
    tools: Mapped[list[Any]] = mapped_column(_JSONB, default=list)
    model_role: Mapped[str] = mapped_column(String(32), default="daily", server_default="daily")
    is_active: Mapped[bool] = mapped_column(default=True, server_default="true")


class AgentTaskRecord(CommonMixin, Base):
    """智能体执行日志表（每次执行一行，成功/失败均留痕）。"""

    __tablename__ = "agent_task_record"

    agent_role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_role.id"))
    task_type: Mapped[str] = mapped_column(String(32))
    input_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    tools_called: Mapped[list[Any]] = mapped_column(_JSONB, default=list)
    model_used: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="success", server_default="success")
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
