"""知识库表：文档文件 + 向量索引（docs/03 §3.6，阶段1）。"""

import uuid
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    BigInteger,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CommonMixin

EMBED_DIM = 1024  # 通义 text-embedding-v3 维度；换 embedding 模型须改此值并重建向量列/索引


class KnowledgeFile(CommonMixin, Base):
    """文档文件表。status: uploaded/parsing/indexed/failed。"""

    __tablename__ = "knowledge_file"

    file_name: Mapped[str] = mapped_column(String(255))
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
    source_ref: Mapped[dict[str, Any] | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=True
    )
