"""TD 运营事件显示别名（数据接口页「运营事件命名」）。

事件原始码（$part_event，如 new_device）→ 中文显示名（如 设备激活），仅供报表/界面可读。
别名按视图分：同一 ta_app_start 在盒子/游戏/APP 三个视图可各自命名，故唯一键 = (view, event_code)。
"""

from sqlalchemy import Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CommonMixin

_ACTIVE = text("is_delete = false")  # 部分唯一索引条件（软删后可重建同键）


class TdEventAlias(CommonMixin, Base):
    """一条事件别名：某视图下某事件码的中文显示名。"""

    __tablename__ = "td_event_alias"
    __table_args__ = (
        Index(
            "uq_td_event_alias", "view", "event_code", unique=True, postgresql_where=_ACTIVE
        ),
    )

    view: Mapped[str] = mapped_column(String(64))  # TD 视图名，如 v_event_4
    event_code: Mapped[str] = mapped_column(String(128))  # $part_event 原始码
    display_name: Mapped[str] = mapped_column(String(128))  # 中文显示名
