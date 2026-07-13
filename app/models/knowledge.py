"""知识库表：知识库集合 + 文档文件 + 向量索引 + 数据接口（docs/13 F2）。

F2：知识集合化 + 范围隔离——文件归属到 knowledge_base（带 scope + 机密标记）；
data_source 为数据接口注册表（密钥走 secret_ref 指向 .env，不存明文）。
"""

import uuid
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CommonMixin

EMBED_DIM = 1024  # 通义 text-embedding-v3 维度；换 embedding 模型须改此值并重建向量列/索引
_JSONB = JSON().with_variant(JSONB(), "postgresql")
_ACTIVE = text("is_delete = false")

# 知识库 scope
SCOPE_COMPANY = "company"  # 公司公共库，全员可见
SCOPE_DEPARTMENT = "department"  # 部门库，默认可见；标机密则仅本部门子树 + 授权 + admin
SCOPE_PERSONAL = "personal"  # 个人专属知识区（高管/总监助理），owner + 授权 + admin


class KnowledgeBase(CommonMixin, Base):
    """知识库集合（带归属 scope + 机密标记）。契约②：默认可见，机密减法隔离。"""

    __tablename__ = "knowledge_base"
    __table_args__ = (Index("uq_kb_code", "code", unique=True, postgresql_where=_ACTIVE),)

    name: Mapped[str] = mapped_column(String(128))
    code: Mapped[str] = mapped_column(String(64))
    scope: Mapped[str] = mapped_column(String(16), default=SCOPE_DEPARTMENT)
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sys_department.id"), nullable=True
    )
    owner_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_role.id"), nullable=True
    )  # personal 时=专属知识区归属的顾问/助理
    is_confidential: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class DataSource(CommonMixin, Base):
    """数据接口注册表。config 仅存非密参数；密钥走 secret_ref 指向 .env 变量名。"""

    __tablename__ = "data_source"
    __table_args__ = (Index("uq_ds_code", "code", unique=True, postgresql_where=_ACTIVE),)

    name: Mapped[str] = mapped_column(String(128))
    code: Mapped[str] = mapped_column(String(64))
    type: Mapped[str] = mapped_column(String(32))  # thinkingdata/feishu_bitable/excel/http_api...
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sys_department.id"), nullable=True
    )  # 公司级=根节点
    config: Mapped[dict[str, Any]] = mapped_column(_JSONB, default=dict)  # 仅非密参数
    secret_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)  # .env 变量名
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class KnowledgeFile(CommonMixin, Base):
    """文档文件表。status: uploaded/parsing/indexed/failed。归属某 knowledge_base。"""

    __tablename__ = "knowledge_file"

    file_name: Mapped[str] = mapped_column(String(255))
    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("knowledge_base.id"))
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    uploader_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sys_user.id"))
    storage_path: Mapped[str] = mapped_column(String(512))  # MinIO bucket/object 或 "inline"
    file_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="uploaded", server_default="uploaded")


class KnowledgeVector(CommonMixin, Base):
    """向量索引表：一行一个文本分块 + 其 embedding。"""

    __tablename__ = "knowledge_vector"
    __table_args__ = (UniqueConstraint("file_id", "chunk_index", name="uq_kv_file_chunk"),)

    file_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("knowledge_file.id"))
    chunk_index: Mapped[int] = mapped_column(Integer)
    chunk_text: Mapped[str] = mapped_column(Text)
    # 主类型 Vector（postgres）；sqlite 单测下降级为 JSON，仅为 metadata.create_all 可跑
    embedding: Mapped[Any] = mapped_column(Vector(EMBED_DIM).with_variant(JSON(), "sqlite"))
    source_ref: Mapped[dict[str, Any] | None] = mapped_column(_JSONB, nullable=True)
