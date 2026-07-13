"""协作空间表（docs/13 F3'）：持久讨论频道 + 消息流。

人机随时讨论；@Agent 触发 AI 顾问发言（复用 run_agent，成本护栏五件套）；
一条消息可「升格」为提案/任务，ref_type/ref_id 回填做溯源。
红线：AI 发言仅参考意见，升格产出仍走既有真人确认闸门。
"""

import uuid
from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, Index, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CommonMixin

_JSONB = JSON().with_variant(JSONB(), "postgresql")

# 发言方类型
SPEAKER_HUMAN = "human"
SPEAKER_AI = "ai"


class DiscussionChannel(CommonMixin, Base):
    """讨论频道（挂组织节点）。部门创建时自动种子一个。"""

    __tablename__ = "discussion_channel"

    name: Mapped[str] = mapped_column(String(128))
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sys_department.id"), nullable=True
    )
    default_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_role.id"), nullable=True
    )  # 前端 @ 缺省目标
    creator_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sys_user.id"), nullable=True
    )  # 种子频道无创建人
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class DiscussionMessage(CommonMixin, Base):
    """频道消息。speaker_id 松引用（真人 sys_user 或 AI agent_role，不加 FK）。"""

    __tablename__ = "discussion_message"
    __table_args__ = (Index("ix_dm_channel", "channel_id", "create_time"),)

    channel_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("discussion_channel.id"))
    speaker_type: Mapped[str] = mapped_column(String(8))  # human / ai
    speaker_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    speaker_name: Mapped[str] = mapped_column(String(64), default="")  # 冗余留痕
    content: Mapped[str] = mapped_column(Text)
    mentioned_agent_ids: Mapped[list[Any]] = mapped_column(_JSONB, default=list)  # @目标
    ai_source_record_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, nullable=True
    )  # AI 发言关联 agent_task_record
    ref_type: Mapped[str | None] = mapped_column(String(16), nullable=True)  # proposal/task
    ref_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)  # 升格产出溯源
