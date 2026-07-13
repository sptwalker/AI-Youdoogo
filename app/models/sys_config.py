"""可编辑运营配置表（docs/13 §3 · F4a）：非密开关/阈值/端点/提示词。

密钥仍留 .env（config.py），本表只存非密配置；改后即时生效（config_service.resolve）。
"""

from typing import Any

from sqlalchemy import JSON, Boolean, Index, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CommonMixin

_JSONB = JSON().with_variant(JSONB(), "postgresql")
_ACTIVE = "is_delete = false"

# category：驱动 F5 前端分组
CAT_LLM = "llm"
CAT_FEISHU = "feishu"
CAT_EMBEDDING = "embedding"
CAT_PROMPT = "prompt"
CAT_FEATURE = "feature"


class SysConfig(CommonMixin, Base):
    """一条可编辑配置项。value 存 JSONB，value_type 驱动前端渲染/校验。"""

    __tablename__ = "sys_config"
    __table_args__ = (Index("uq_config_key", "key", unique=True, postgresql_where=_ACTIVE),)

    key: Mapped[str] = mapped_column(String(64))
    value: Mapped[Any] = mapped_column(_JSONB)
    value_type: Mapped[str] = mapped_column(String(16), default="string")  # string/int/bool/text
    category: Mapped[str] = mapped_column(String(32), default=CAT_FEATURE)
    is_editable: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    updated_by: Mapped[Any] = mapped_column(Uuid, nullable=True)
