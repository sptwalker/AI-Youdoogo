"""LLM 用量记录表（docs/09 §5 阶段1：用量从日志升级为数据库记录 + 日预算告警）。"""

import uuid

from sqlalchemy import ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.database.model import Base, CommonMixin


class LlmCallLog(CommonMixin, Base):
    """一次 LLM 调用的用量留痕（角色/模型/token/耗时/成败 + 业务关联）。"""

    __tablename__ = "llm_call_log"

    role: Mapped[str] = mapped_column(String(32))  # app/llm/roles.py 的角色键
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)  # 实际命中模型
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    total_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="success", server_default="success")
    # 业务关联（松引用，不加 FK 避免跨模块耦合）
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    task_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("sys_department.id"), nullable=True
    )  # F4a 部门级预算归集
    workflow_run_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("workflow_run.id"), nullable=True
    )
    workflow_step_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("workflow_step.id"), nullable=True
    )
    attempt_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    trace_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
