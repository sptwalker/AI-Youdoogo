"""SQLAlchemy adapter for Knowledge Indexing commands."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.knowledge.knowledge_indexing.contracts import (
    IndexedDocument,
    IndexFeishuDocumentCommand,
    IndexFileCommand,
    IndexTextCommand,
)
from app.contexts.foundations.knowledge.knowledge_indexing.infrastructure import (
    sqlalchemy_index,
)
from app.models.knowledge import KnowledgeFile


def _snapshot(record: KnowledgeFile) -> IndexedDocument:
    return IndexedDocument(
        id=record.id,
        file_name=record.file_name,
        knowledge_base_id=record.knowledge_base_id,
        category=record.category,
        uploader_id=record.uploader_id,
        storage_path=record.storage_path,
        file_size=record.file_size,
        mime_type=record.mime_type,
        status=record.status,
        create_time=record.create_time,
    )


class SqlAlchemyDocumentIndexGateway:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_documents(
        self, *, limit: int, knowledge_base_id: uuid.UUID | None = None
    ) -> tuple[IndexedDocument, ...]:
        statement = (
            select(KnowledgeFile)
            .where(KnowledgeFile.is_delete.is_(False))
            .order_by(KnowledgeFile.create_time.desc())
            .limit(limit)
        )
        if knowledge_base_id is not None:
            statement = statement.where(
                KnowledgeFile.knowledge_base_id == knowledge_base_id
            )
        return tuple(
            _snapshot(record)
            for record in (await self._session.execute(statement)).scalars()
        )

    async def index_text(self, command: IndexTextCommand) -> IndexedDocument:
        record = await sqlalchemy_index.ingest_text(
            self._session,
            title=command.title,
            text=command.text,
            uploader_id=command.uploader_id,
            knowledge_base_id=command.knowledge_base_id,
            category=command.category,
            file_id=command.document_id,
            publish_events=command.publish_events,
        )
        return _snapshot(record)

    async def index_file(self, command: IndexFileCommand) -> IndexedDocument:
        record = await sqlalchemy_index.ingest_file(
            self._session,
            file_name=command.file_name,
            content=command.content,
            mime_type=command.mime_type,
            uploader_id=command.uploader_id,
            knowledge_base_id=command.knowledge_base_id,
            category=command.category,
        )
        return _snapshot(record)

    async def index_feishu_document(self, command: IndexFeishuDocumentCommand) -> IndexedDocument:
        record = await sqlalchemy_index.ingest_feishu_doc(
            self._session,
            document_id=command.document_id,
            uploader_id=command.uploader_id,
            knowledge_base_id=command.knowledge_base_id,
            category=command.category,
        )
        return _snapshot(record)

    async def remove(self, document_id: uuid.UUID) -> None:
        await sqlalchemy_index.delete_file(self._session, document_id)

    async def move(self, document_id: uuid.UUID, knowledge_base_id: uuid.UUID) -> IndexedDocument:
        record = await sqlalchemy_index.move_file(self._session, document_id, knowledge_base_id)
        return _snapshot(record)
