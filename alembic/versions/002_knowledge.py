"""knowledge: knowledge_file / knowledge_vector（含 pgvector 扩展与 hnsw 索引）

Revision ID: 002_knowledge
Revises: 001_baseline
Create Date: 2026-07-12

"""
from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "002_knowledge"
down_revision: str | None = "001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBED_DIM = 1024  # 与 app/models/knowledge.py 保持一致


def _common_columns() -> list[sa.Column]:
    """文档03通用基础字段（同 001_baseline）。"""
    return [
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("create_time", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("update_time", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_delete", sa.Boolean(), server_default="false", nullable=False),
    ]


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "knowledge_file",
        *_common_columns(),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("category", sa.String(64), nullable=True),
        sa.Column("uploader_id", sa.Uuid(), sa.ForeignKey("sys_user.id"), nullable=False),
        sa.Column("storage_path", sa.String(512), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=True),
        sa.Column("mime_type", sa.String(128), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="uploaded"),
    )
    op.create_table(
        "knowledge_vector",
        *_common_columns(),
        sa.Column("file_id", sa.Uuid(), sa.ForeignKey("knowledge_file.id"), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("chunk_text", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(EMBED_DIM), nullable=False),
        sa.Column("source_ref", postgresql.JSONB(), nullable=True),
        sa.UniqueConstraint("file_id", "chunk_index", name="uq_kv_file_chunk"),
    )
    op.execute(
        "CREATE INDEX ix_kv_embedding ON knowledge_vector "
        "USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.drop_table("knowledge_vector")
    op.drop_table("knowledge_file")
    # vector 扩展保留：可能被其他对象依赖，删除风险大于收益
