"""收件箱条目读态（docs/27 §六，归属 work_desktop）。

待办队列是 5 类来源的纯读投影，本身无稳定聚合。本表按 (owner_user_id, kind, source_id)
落「已读 / 已处理 / AI 摘要」持久态，供去重合并与批量处理复用。source_id 是跨多张来源表的
软引用，故不加外键。优先级分数为派生量（依赖权重与当前时间），刻意不落库以免过期——由读侧现算。
"""

import uuid

from sqlalchemy import Boolean, ForeignKey, Index, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.database.model import Base, CommonMixin


class InboxItemState(CommonMixin, Base):
    """某真人对某待办来源的读态。"""

    __tablename__ = "inbox_item_state"
    __table_args__ = (
        Index(
            "uq_inbox_owner_source",
            "owner_user_id",
            "kind",
            "source_id",
            unique=True,
        ),
    )

    owner_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sys_user.id"))
    kind: Mapped[str] = mapped_column(String(16))  # task / proposal / resolution / collab
    source_id: Mapped[uuid.UUID] = mapped_column(Uuid)  # 源聚合 id（软引用，跨表故无 FK）
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    is_processed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    ai_summary: Mapped[str | None] = mapped_column(Text, nullable=True)  # AI 一句话摘要（阶段D填）
