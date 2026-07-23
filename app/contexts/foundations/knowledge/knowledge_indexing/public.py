"""Stable Knowledge Indexing application facade for outer adapters."""

from app.contexts.foundations.knowledge.knowledge_indexing.entrypoints.operations import (
    index_feishu_document as index_feishu_document,
)
from app.contexts.foundations.knowledge.knowledge_indexing.entrypoints.operations import (
    index_file as index_file,
)
from app.contexts.foundations.knowledge.knowledge_indexing.entrypoints.operations import (
    index_text as index_text,
)
from app.contexts.foundations.knowledge.knowledge_indexing.entrypoints.operations import (
    list_documents as list_documents,
)
from app.contexts.foundations.knowledge.knowledge_indexing.entrypoints.operations import (
    move_document as move_document,
)
from app.contexts.foundations.knowledge.knowledge_indexing.entrypoints.operations import (
    remove_document_index as remove_document_index,
)
