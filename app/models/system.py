"""系统基础表：用户/部门(组织树)/角色。

F1(阶段F1)：部门树化——公司=根节点、两级部门、物化路径、真人主管。
软删×唯一约束系统性修复：业务唯一键统一用「部分唯一索引 WHERE is_delete=false」，
使"软删后可重建同名"（现有 unique=True 会撞库）。CEO=最高管理员(真人)，不设 CEO Agent。
"""

import uuid

from sqlalchemy import ForeignKey, Index, Integer, SmallInteger, String, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CommonMixin

# 组织节点类型
COMPANY = "company"
DEPT_L1 = "dept_l1"
DEPT_L2 = "dept_l2"

_ACTIVE = text("is_delete = false")  # 部分唯一索引条件


class SysDepartment(CommonMixin, Base):
    """组织节点表（公司根 / 一级部门 / 二级部门统一为一棵树）。"""

    __tablename__ = "sys_department"
    __table_args__ = (
        # 同父下部门名唯一；code 全局唯一——均排除软删行
        Index("uq_dept_parent_name", "parent_id", "name", unique=True, postgresql_where=_ACTIVE),
        Index("uq_dept_code", "code", unique=True, postgresql_where=_ACTIVE),
        Index("ix_dept_path", "path"),
        Index("ix_dept_parent", "parent_id"),
    )

    name: Mapped[str] = mapped_column(String(64))
    code: Mapped[str] = mapped_column(String(32))
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("sys_department.id"), nullable=True
    )  # 公司根为 NULL
    node_type: Mapped[str] = mapped_column(String(16), default=DEPT_L1, server_default=DEPT_L1)
    level: Mapped[int] = mapped_column(SmallInteger, default=1, server_default="1")  # 0公司/1/2
    path: Mapped[str] = mapped_column(
        String(255), default="", server_default=""
    )  # 物化路径 /{root}/{l1}/{l2}/
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # 该部门对应的真人主管（跨部门协作确认/复核由此人执行；根节点=CEO/顶层admin）
    supervisor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("sys_user.id", use_alter=True, name="fk_dept_supervisor"), nullable=True
    )


class SysRole(CommonMixin, Base):
    """角色字典表。首版 admin / executive / member。"""

    __tablename__ = "sys_role"
    __table_args__ = (Index("uq_role_code", "code", unique=True, postgresql_where=_ACTIVE),)

    code: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(64))


class SysUser(CommonMixin, Base):
    """系统用户表（真人；管理/监督层，挂部门）。role_code=admin 即 CEO/最高权限。"""

    __tablename__ = "sys_user"
    __table_args__ = (
        Index("uq_user_username", "username", unique=True, postgresql_where=_ACTIVE),
        # open_id 是用户在当前飞书应用内的不可变身份；软删行也保留占用，避免身份被静默重绑。
        Index(
            "uq_user_feishu_open_id",
            "feishu_open_id",
            unique=True,
            postgresql_where=text("feishu_open_id IS NOT NULL"),
        ),
    )

    username: Mapped[str] = mapped_column(String(64))
    password_hash: Mapped[str] = mapped_column(String(255))
    real_name: Mapped[str] = mapped_column(String(64), default="")
    role_code: Mapped[str] = mapped_column(String(32), default="member")  # 冗余角色码，查询免联表
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("sys_department.id"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(default=True, server_default="true")
    feishu_open_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
