"""时间管理三聚合表（docs/27 阶段 B2）：日程 / 专注番茄钟 / 时间记录，归 time_management Context。

个人数据默认仅本人可见，行级隔离按 owner_id（docs/16 P0 / docs/27 §四）；命中他人一律当不存在。
红线：智能排程只出建议（status=suggested），真人 confirm 才生效；番茄钟拦截只影响发给本人的通知。
linked_task_id/ref_task_id 为软引用（不建 FK，避免跨 Context 表耦合），仅存 id。
"""

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import DateTime

from app.platform.database.model import Base, CommonMixin


class Schedule(CommonMixin, Base):
    """日程。source=manual 直接 confirmed；source=suggested 建议态，真人 confirm 才生效。"""

    __tablename__ = "schedule"

    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sys_user.id"))
    title: Mapped[str] = mapped_column(String(200))
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(16), default="manual", server_default="manual")
    status: Mapped[str] = mapped_column(String(16), default="confirmed", server_default="confirmed")
    linked_task_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)


class FocusSession(CommonMixin, Base):
    """专注/番茄钟。active 期间 intercept_notifications=True 则拦截发给本人的点对点通知。"""

    __tablename__ = "focus_session"

    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sys_user.id"))
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    planned_minutes: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="active", server_default="active")
    intercept_notifications: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true"
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TimeLog(CommonMixin, Base):
    """时间记录：按 category 记本人某日耗时（分钟），供周复盘聚合。ref_task_id 软引用。"""

    __tablename__ = "time_log"

    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sys_user.id"))
    category: Mapped[str] = mapped_column(String(64))
    minutes: Mapped[int] = mapped_column(Integer)
    logged_date: Mapped[date] = mapped_column(Date)
    ref_task_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
