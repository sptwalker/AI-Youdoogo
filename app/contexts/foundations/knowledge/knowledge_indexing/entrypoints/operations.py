"""Request-scoped Knowledge Indexing operations."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.knowledge.knowledge_indexing.application.use_cases import (
    KnowledgeIndexing,
)
from app.contexts.foundations.knowledge.knowledge_indexing.contracts import (
    IndexedDocument,
    IndexFeishuDocumentCommand,
    IndexFileCommand,
    IndexTextCommand,
)
from app.contexts.foundations.knowledge.knowledge_indexing.infrastructure import (
    sqlalchemy_gateway,
)


def _indexing(session: AsyncSession) -> KnowledgeIndexing:
    return KnowledgeIndexing(sqlalchemy_gateway.SqlAlchemyDocumentIndexGateway(session))


async def list_documents(
    session: AsyncSession, *, limit: int = 100
) -> tuple[IndexedDocument, ...]:
    return await _indexing(session).list_documents(limit=limit)


async def index_text(session: AsyncSession, command: IndexTextCommand) -> IndexedDocument:
    return await _indexing(session).index_text(command)


async def index_file(session: AsyncSession, command: IndexFileCommand) -> IndexedDocument:
    return await _indexing(session).index_file(command)


async def index_feishu_document(
    session: AsyncSession, command: IndexFeishuDocumentCommand
) -> IndexedDocument:
    return await _indexing(session).index_feishu_document(command)


async def remove_document_index(session: AsyncSession, document_id: uuid.UUID) -> None:
    await _indexing(session).remove(document_id)


async def move_document(
    session: AsyncSession, document_id: uuid.UUID, knowledge_base_id: uuid.UUID
) -> IndexedDocument:
    return await _indexing(session).move(document_id, knowledge_base_id)
