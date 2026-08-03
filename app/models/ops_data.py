"""平台运营部业务数据表（阶段2）。

运营日指标：Excel 上传解析后落此表，供运营日报/异常告警取数。
docs/03 §3.7：业务时序数据阶段4 才转 TimescaleDB hypertable，本阶段先普通表
（按 (stat_date, product) 唯一，重复上传幂等 upsert）。
"""

import uuid
from datetime import date

from sqlalchemy import Date, Float, ForeignKey, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.database.model import Base, CommonMixin


class OpsDailyMetric(CommonMixin, Base):
    """平台运营日指标（一天一产品一行）。"""

    __tablename__ = "ops_daily_metric"
    __table_args__ = (UniqueConstraint("stat_date", "product", name="uq_ops_date_product"),)

    stat_date: Mapped[date] = mapped_column(Date)
    product: Mapped[str] = mapped_column(String(64))
    dau: Mapped[int] = mapped_column(Integer)
    new_users: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retention_d1: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(32), default="excel", server_default="excel")
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("sys_department.id"), nullable=True
    )  # F4a 部门切片
