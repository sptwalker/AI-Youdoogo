"""Knowledge Indexing gateway port."""

from __future__ import annotations

import uuid
from typing import Protocol

from app.contexts.foundations.knowledge.knowledge_indexing.contracts import (
    IndexedDocument,
    IndexFeishuDocumentCommand,
    IndexFileCommand,
    IndexTextCommand,
)


class DocumentIndexGateway(Protocol):
    async def list_documents(
        self, *, limit: int, knowledge_base_id: uuid.UUID | None = None
    ) -> tuple[IndexedDocument, ...]: ...

    async def index_text(self, command: IndexTextCommand) -> IndexedDocument: ...

    async def index_file(self, command: IndexFileCommand) -> IndexedDocument: ...

    async def index_feishu_document(
        self, command: IndexFeishuDocumentCommand
    ) -> IndexedDocument: ...

    async def remove(self, document_id: uuid.UUID) -> None: ...

    async def move(
        self, document_id: uuid.UUID, knowledge_base_id: uuid.UUID
    ) -> IndexedDocument: ...
