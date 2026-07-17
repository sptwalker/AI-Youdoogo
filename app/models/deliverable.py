"""智能体文件交付物（docs/13 §11 交付技能）。

AI 把产出整理成 CSV/XLSX/文档，落 MinIO，记一行本表交付到真人工作桌面「文件交付区」。
owner_user_id = 交付给谁（桌面归属，作用域）；agent_id/agent_name 冗余记交付方（AI 可删，留名字）。
红线：交付物只是文件，下载即用，不触发任何业务决议。
"""

import uuid

from sqlalchemy import ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CommonMixin


class Deliverable(CommonMixin, Base):
    """一份交付到某真人桌面的文件。"""

    __tablename__ = "deliverable"
    __table_args__ = (Index("ix_deliverable_owner_time", "owner_user_id", "create_time"),)

    owner_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sys_user.id"))
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_role.id"), nullable=True
    )  # 交付方 AI（软引用：AI 删除后仍保留交付物，故 nullable）
    agent_name: Mapped[str] = mapped_column(String(64), default="", server_default="")
    file_name: Mapped[str] = mapped_column(String(255))
    file_format: Mapped[str] = mapped_column(String(8))  # csv / xlsx / md / txt
    storage_path: Mapped[str] = mapped_column(String(512))  # MinIO bucket/object
    file_size: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
