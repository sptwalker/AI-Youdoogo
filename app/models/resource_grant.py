"""资源授权例外表（docs/13 §1.3 · F4b）：唯一权限表，只存默认可见性之外的显式授权。

红线固化：grant 只授「内容访问权」（read/write/admin），**绝不授「生效权」**。
grant 到某节点（grantee_type=department）= 覆盖其子树，读时判定。
resource_id/grantee_id 多态松引用，不加 FK。
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CommonMixin

# grantee 类型（docs 决策⑪：砍 role 级授权，只 user/agent/department）
GRANTEE_USER = "user"
GRANTEE_AGENT = "agent"
GRANTEE_DEPARTMENT = "department"

# 权限档（只授内容访问，不授生效）
PERM_READ = "read"
PERM_WRITE = "write"
PERM_ADMIN = "admin"


class ResourceGrant(CommonMixin, Base):
    """一条显式授权例外。grantee 可为真人/AI/部门；部门授权覆盖其子树。"""

    __tablename__ = "resource_grant"
    __table_args__ = (
        Index("ix_grant_lookup", "resource_type", "grantee_type", "grantee_id"),
    )

    resource_type: Mapped[str] = mapped_column(String(32))  # knowledge_base/data_source/...
    resource_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    grantee_type: Mapped[str] = mapped_column(String(16))  # user/agent/department
    grantee_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    perm: Mapped[str] = mapped_column(String(16), default=PERM_READ, server_default=PERM_READ)
    granted_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sys_user.id"), nullable=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
