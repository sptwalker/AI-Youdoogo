"""会议决策表（docs/03 §3.5，阶段4 下半场）：会议 + 讨论 + 投票 + 决议。

红线（docs/04）：决议须真人确认（is_confirmed）才生效；AI 票仅参考，真人票决定；
仅已确认决议可转任务卡。
"""

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.database.model import Base, CommonMixin

_JSONB = JSON().with_variant(JSONB(), "postgresql")

# 会议状态
SCHEDULED = "scheduled"
IN_PROGRESS = "in_progress"
CLOSED = "closed"


class MeetingInfo(CommonMixin, Base):
    """会议主表。"""

    __tablename__ = "meeting_info"

    title: Mapped[str] = mapped_column(String(200))
    meeting_type: Mapped[str] = mapped_column(String(32), default="decision")
    status: Mapped[str] = mapped_column(String(16), default=SCHEDULED, server_default=SCHEDULED)
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sys_department.id"), nullable=True
    )  # 归属部门（F3'；存量会议 NULL=临时会议）
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    creator_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sys_user.id"))
    participants: Mapped[list[Any]] = mapped_column(_JSONB, default=list)  # [{type,id,name}]
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)  # 自动会议纪要


class MeetingDiscuss(CommonMixin, Base):
    """会议发言记录（真人或 AI 专家）。create_time 即发言时间。"""

    __tablename__ = "meeting_discuss"

    meeting_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("meeting_info.id"))
    speaker_type: Mapped[str] = mapped_column(String(8))  # human / ai
    speaker_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    speaker_name: Mapped[str] = mapped_column(String(64), default="")
    content: Mapped[str] = mapped_column(Text)


class MeetingVote(CommonMixin, Base):
    """投票记录。voter_type 区分真人/AI（红线：AI 票仅参考）。"""

    __tablename__ = "meeting_vote"

    meeting_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("meeting_info.id"))
    subject: Mapped[str] = mapped_column(String(200))  # 表决对象（提案编号/议题）
    voter_type: Mapped[str] = mapped_column(String(8))  # human / ai
    voter_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    choice: Mapped[str] = mapped_column(String(16))  # approve / reject / abstain
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)


class MeetingResolution(CommonMixin, Base):
    """会议决议。红线：is_confirmed=True（真人确认）才生效；仅确认后可转任务卡。"""

    __tablename__ = "meeting_resolution"

    meeting_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("meeting_info.id"))
    content: Mapped[str] = mapped_column(Text)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)  # 负责人
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    converted_task_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
