"""提案卡表（docs/03 §3.4，阶段4）：提案主表 + 评审记录（AI预研 + 人工评审）。"""

import uuid

from sqlalchemy import ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CommonMixin

# 提案状态：草稿→预研中→已预研→(真人)通过/驳回
DRAFT = "draft"
RESEARCHING = "researching"
REVIEWED = "reviewed"
APPROVED = "approved"
REJECTED = "rejected"


class ProposalCard(CommonMixin, Base):
    """提案主表。approved 仅能由真人评审置位（docs/04 红线：决议须真人确认）。"""

    __tablename__ = "proposal_card"

    code: Mapped[str] = mapped_column(String(32), unique=True)
    title: Mapped[str] = mapped_column(String(200))
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sys_department.id"), nullable=True
    )
    background: Mapped[str] = mapped_column(Text)
    plan: Mapped[str] = mapped_column(Text)
    benefit_risk: Mapped[str | None] = mapped_column(Text, nullable=True)
    priority: Mapped[str] = mapped_column(String(16), default="normal", server_default="normal")
    status: Mapped[str] = mapped_column(String(16), default=DRAFT, server_default=DRAFT)
    creator_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sys_user.id"))
    converted_task_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)  # 转出的任务卡


class ProposalReview(CommonMixin, Base):
    """提案评审记录。review_type: ai_research（会商专家预研）/ human（真人评审）。"""

    __tablename__ = "proposal_review"

    proposal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("proposal_card.id"))
    review_type: Mapped[str] = mapped_column(String(16))
    conclusion: Mapped[str] = mapped_column(Text)
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)  # 真人评审人
    decision: Mapped[str | None] = mapped_column(String(16), nullable=True)  # approve/reject
