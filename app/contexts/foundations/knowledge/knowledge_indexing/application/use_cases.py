"""Focused Knowledge Indexing application service."""

from __future__ import annotations

import uuid

from app.contexts.foundations.knowledge.knowledge_indexing.application.ports import (
    DocumentIndexGateway,
)
from app.contexts.foundations.knowledge.knowledge_indexing.contracts import (
    IndexedDocument,
    IndexFeishuDocumentCommand,
    IndexFileCommand,
    IndexTextCommand,
)


class KnowledgeIndexing:
    def __init__(self, gateway: DocumentIndexGateway) -> None:
        self._gateway = gateway

    async def list_documents(
        self, *, limit: int, knowledge_base_id: uuid.UUID | None = None
    ) -> tuple[IndexedDocument, ...]:
        return await self._gateway.list_documents(
            limit=limit, knowledge_base_id=knowledge_base_id
        )

    async def index_text(self, command: IndexTextCommand) -> IndexedDocument:
        return await self._gateway.index_text(command)

    async def index_file(self, command: IndexFileCommand) -> IndexedDocument:
        return await self._gateway.index_file(command)

    async def index_feishu_document(self, command: IndexFeishuDocumentCommand) -> IndexedDocument:
        return await self._gateway.index_feishu_document(command)

    async def remove(self, document_id: uuid.UUID) -> None:
        await self._gateway.remove(document_id)

    async def move(self, document_id: uuid.UUID, knowledge_base_id: uuid.UUID) -> IndexedDocument:
        return await self._gateway.move(document_id, knowledge_base_id)
