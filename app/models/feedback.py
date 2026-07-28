"""智能体输出反馈评分表（docs/06 阶段5：反馈评分 → 提示词优化主链）。"""

import uuid

from sqlalchemy import ForeignKey, Integer, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.database.model import Base, CommonMixin


class AgentFeedback(CommonMixin, Base):
    """对一条智能体执行记录的人工评分（1~5）+ 评语，驱动提示词优化。"""

    __tablename__ = "agent_feedback"

    task_record_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_task_record.id"))
    rater_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    score: Mapped[int] = mapped_column(Integer)  # 1~5
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
