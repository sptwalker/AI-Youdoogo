"""智能体表：角色配置 + 执行留痕（docs/03 §3.2，阶段1~2）。

agent_task_record 是「所有AI操作必须留痕、数据可溯源」红线的落地表（docs/04 §1）。
"""

import uuid
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.database.model import Base, CommonMixin

# JSONB 主类型；sqlite 单测下降级为通用 JSON，仅为 metadata.create_all 可跑
_JSONB = JSON().with_variant(JSONB(), "postgresql")
_ACTIVE = text("is_delete = false")

# 员工层级
TIER_EXEC = "exec"  # 公司高管（挂公司根，report_to=NULL，CEO=真人不在此列）
TIER_DIRECTOR = "director"  # 部门总监（挂一级部门）
TIER_MEMBER = "member"  # 普通员工


class AgentRole(CommonMixin, Base):
    """智能体角色 = AI 员工。tier 组织层级；model_role LLM 档位(daily/reasoning)，二者正交。"""

    __tablename__ = "agent_role"
    __table_args__ = (
        Index("uq_agent_code", "code", unique=True, postgresql_where=_ACTIVE),
        Index("uq_agent_name", "name", unique=True, postgresql_where=_ACTIVE),
        Index("ix_agent_dept", "department_id"),
        Index("ix_agent_owner_user", "owner_user_id"),
    )

    code: Mapped[str | None] = mapped_column(String(64), nullable=True)  # 稳定种子键 exec_cpo/dir_*
    name: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(64), default="", server_default="")  # 显示职位名
    tier: Mapped[str] = mapped_column(String(16), default=TIER_MEMBER, server_default=TIER_MEMBER)
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sys_department.id"), nullable=True
    )
    report_to_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_role.id"), nullable=True
    )  # 汇报线 member→director→exec
    # 非空=某真人的专属助理（不进组织树/智能体列表，只在其本人工作桌面用）
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sys_user.id"), nullable=True
    )
    duty: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_template: Mapped[str] = mapped_column(Text)
    # 工具/额外授权提示（访问控制主职走 scope 推导 + resource_grant）
    permission_scope: Mapped[dict[str, Any]] = mapped_column(_JSONB, default=dict)
    tools: Mapped[list[Any]] = mapped_column(_JSONB, default=list)
    model_role: Mapped[str] = mapped_column(String(32), default="daily", server_default="daily")
    # 骨架保护：种子高管/总监不被误删
    is_seed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    is_active: Mapped[bool] = mapped_column(default=True, server_default="true")
    # 当前已发布的不可变执行快照指针（Phase 3 Module 2 / docs/23 §4.2）。
    # ponytail: 软指针不加 FK，避免与 expert_release.expert_id 成循环外键（破坏 sqlite create_all
    # 排序）；真链由 expert_release 行反向 FK 保证，回滚=改此指针到旧 version。
    current_release_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)


class ExpertRelease(CommonMixin, Base):
    """专家执行定义的不可变发布快照（Phase 3 Module 2 / docs/23 §4.2）。

    每次发布把 agent_role 当前的 Prompt/模型档/工具/权限/duty 冻结成一行；
    ``(expert_id, version_no)`` 唯一、只增不改。业务表 ``agent_role.current_release_id`` 指向
    最新已发布快照；回滚（Module 6）= 改指针到旧 version。``create_time`` 即发布时刻。
    独立物理表为后续 Expert 平台拆分留缝，当前仍单库单进程。
    """

    __tablename__ = "expert_release"
    __table_args__ = (Index("uq_expert_release_version", "expert_id", "version_no", unique=True),)

    expert_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_role.id"))
    version_no: Mapped[int] = mapped_column(Integer)
    prompt_template: Mapped[str] = mapped_column(Text)
    model_role: Mapped[str] = mapped_column(String(32))
    permission_scope: Mapped[dict[str, Any]] = mapped_column(_JSONB, default=dict)
    tools: Mapped[list[Any]] = mapped_column(_JSONB, default=list)
    duty: Mapped[str | None] = mapped_column(Text, nullable=True)
    released_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    # 发布时冻结的评测证据（Module 3 / docs/23 §4.3）：门控本版发布的聚合分 + 用例数；
    # 空=未附评测证据。评测只产分不自动发布，是否发布仍真人确认（AI 红线）。
    eval_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    eval_case_count: Mapped[int | None] = mapped_column(Integer, nullable=True)


class AgentTaskRecord(CommonMixin, Base):
    """智能体执行日志表（每次执行一行，成功/失败均留痕）。"""

    __tablename__ = "agent_task_record"

    agent_role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_role.id"))
    task_type: Mapped[str] = mapped_column(String(32))
    input_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    tools_called: Mapped[list[Any]] = mapped_column(_JSONB, default=list)
    # 检索引用溯源（H2.3）：本次注入用了哪些知识库片段 [{file_id,file_name,chunk_index}]。
    # 让"某AI产出用了哪些资料"事后可精确重建，不再只临时拼进 prompt。
    sources: Mapped[list[Any]] = mapped_column(_JSONB, default=list, server_default="[]")
    model_used: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="success", server_default="success")
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    workflow_run_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("workflow_run.id"), nullable=True
    )
    workflow_step_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("workflow_step.id"), nullable=True
    )
    attempt_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    trace_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
