"""系统基础表：用户/部门/角色（首版简化3角色，四级RBAC按文档03预留扩展）。"""

import uuid

from sqlalchemy import Boolean, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CommonMixin


class SysDepartment(CommonMixin, Base):
    """部门表。"""

    __tablename__ = "sys_department"

    name: Mapped[str] = mapped_column(String(64), unique=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)


class SysRole(CommonMixin, Base):
    """角色字典表。首版仅 admin / executive / member 三行。"""

    __tablename__ = "sys_role"

    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(64))


class SysUser(CommonMixin, Base):
    """系统用户表（首批为管理层小范围用户）。"""

    __tablename__ = "sys_user"

    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    real_name: Mapped[str] = mapped_column(String(64), default="")
    role_code: Mapped[str] = mapped_column(String(32), default="member")  # 冗余角色码，查询免联表
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("sys_department.id"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
