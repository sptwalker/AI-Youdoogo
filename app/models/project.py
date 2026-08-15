"""项目表（docs/27 阶段 A1）：个人工作台的任务分组容器，归 project_management Context 所有。

Project 是与任务卡区分开的独立聚合（docs/27 §5.3 裁决 #1）；任务卡后续（A2）持可空 project_id 引用。
status=active|archived，归档为软生命周期标记（非删除，docs/27 §5.2）。个人数据默认仅本人可见，
行级隔离按 owner_id（docs/16 P0 / docs/27 §四）。
"""

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import DateTime

from app.platform.database.model import Base, CommonMixin


class Project(CommonMixin, Base):
    """项目主表。owner_id 为归属人（个人工作台）；department_id 可空（跨部门项目留白）。"""

    __tablename__ = "project"

    name: Mapped[str] = mapped_column(String(200))
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sys_user.id"))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="active", server_default="active")
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sys_department.id"), nullable=True
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
