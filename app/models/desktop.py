"""工作桌面持久对话消息（专属助理 + 圆桌多AI）。

每个真人一条连续消息流（owner_user_id 归属），桌面展示最近 N 天（默认10）；
更早的消息由 Assistant Conversations 归档用例写入助理 personal KB 后**硬删**，
故本表只留近期热数据。speaker_name 冗余存发言时的显示名，保证归档/渲染稳定。
"""

import uuid

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CommonMixin

SPEAKER_USER = "user"
SPEAKER_AI = "ai"


class DesktopMessage(CommonMixin, Base):
    """一条工作桌面对话消息（真人或某 AI 的发言）。"""

    __tablename__ = "desktop_message"
    __table_args__ = (Index("ix_desktop_msg_owner_time", "owner_user_id", "create_time"),)

    owner_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sys_user.id"))
    speaker_type: Mapped[str] = mapped_column(String(8))  # user / ai
    speaker_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_role.id"), nullable=True
    )  # AI 发言时=哪个智能体；user 发言为 NULL
    speaker_name: Mapped[str] = mapped_column(String(64), default="", server_default="")
    content: Mapped[str] = mapped_column(Text)
