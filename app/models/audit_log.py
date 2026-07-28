"""审计日志表（docs/13 契约③ · F4a）：真人生效动作 + 配置/组织/权限变更强制留痕。

追加式（只写不改）；detail 落库前对密钥字段打码（audit_service._mask）。
"""

import uuid
from typing import Any

from sqlalchemy import JSON, ForeignKey, Index, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.database.model import Base, CommonMixin

_JSONB = JSON().with_variant(JSONB(), "postgresql")


class AuditLog(CommonMixin, Base):
    """一条真人操作留痕。actor_id 为 None=系统动作。"""

    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_action", "action"),
        Index("ix_audit_actor", "actor_id"),
        Index("ix_audit_target", "target_type", "target_id"),
    )

    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sys_user.id"), nullable=True
    )
    actor_role: Mapped[str | None] = mapped_column(String(32), nullable=True)  # 角色快照
    action: Mapped[str] = mapped_column(String(48))  # task.accept / config.update ...
    target_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    summary: Mapped[str] = mapped_column(Text)
    detail: Mapped[dict[str, Any] | None] = mapped_column(_JSONB, nullable=True)  # 密钥打码后
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    result: Mapped[str] = mapped_column(String(16), default="ok", server_default="ok")
