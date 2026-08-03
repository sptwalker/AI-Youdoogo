"""跨部门协作治理表（docs/13 §2.2 · F4c，只做结构）。

collab_authorization：既定工作流授权容器——目标部门主管预授权「源部门→本部门某类协作」通道。
collab_request：主管复核队列载体——跨部门协作请求，目标部门主管复核（分发闸门）。
红线：复核只放松「分发闸门（谁准许开始干活）」；产出的「生效」永远真人验收，本表不授生效权。
跨部门自动编排链（自动分发/匹配/回流）留「业务工作流」未来阶段，本阶段只落结构。
"""

import uuid

from sqlalchemy import Boolean, ForeignKey, Index, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.database.model import Base, CommonMixin

# 复核请求状态
REQ_PENDING = "pending"
REQ_APPROVED = "approved"
REQ_REJECTED = "rejected"

# 风险档（红线类别恒高；分析/草拟/取数/报告/预研默认低）
RISK_LOW = "low"
RISK_HIGH = "high"


class CollabAuthorization(CommonMixin, Base):
    """既定工作流授权：目标部门预授权源部门某类协作（未来自动分发+事后复核）。"""

    __tablename__ = "collab_authorization"
    __table_args__ = (
        Index("ix_collab_auth_pair", "source_department_id", "target_department_id"),
    )

    source_department_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sys_department.id"))
    target_department_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sys_department.id"))
    collab_type: Mapped[str] = mapped_column(String(64))  # 协作类别（取数/预研/草拟...）
    authorized_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sys_user.id"), nullable=True
    )  # 目标部门主管/admin
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class CollabRequest(CommonMixin, Base):
    """跨部门协作请求（主管复核队列一行）。目标部门主管复核 approve/reject。"""

    __tablename__ = "collab_request"
    __table_args__ = (
        Index("ix_collab_req_target", "target_department_id", "status"),
        Index("uq_collab_req_idempotency", "idempotency_key", unique=True),
    )

    source_department_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sys_department.id"), nullable=True
    )
    target_department_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sys_department.id"))
    title: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)  # 风险分级依据
    risk_level: Mapped[str] = mapped_column(String(16), default=RISK_LOW, server_default=RISK_LOW)
    status: Mapped[str] = mapped_column(String(16), default=REQ_PENDING, server_default=REQ_PENDING)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)  # 松引用真人/AI
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 复核通过后未来接自动分发产出的任务卡（本阶段留空）
    ref_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    ref_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
