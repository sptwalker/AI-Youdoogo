"""SQLAlchemy adapter around hybrid retrieval and cited answering."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.knowledge.knowledge_retrieval.contracts import (
    AnswerKnowledgeQuery,
    Citation,
    KnowledgeAnswer,
    KnowledgeHit,
    KnowledgeRetrievalArmDiagnostics,
    SearchKnowledgeQuery,
    SearchKnowledgeResult,
)
from app.contexts.foundations.knowledge.knowledge_retrieval.infrastructure import (
    sqlalchemy_retrieval,
)


class SqlAlchemyKnowledgeRetrievalGateway:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def search(self, query: SearchKnowledgeQuery) -> SearchKnowledgeResult:
        visible = (
            list(query.visible_knowledge_base_ids)
            if query.visible_knowledge_base_ids is not None
            else None
        )
        hits = await sqlalchemy_retrieval.search(
            self._session,
            query.query,
            top_k=query.top_k,
            visible_kb_ids=visible,
        )
        return SearchKnowledgeResult(
            hits=tuple(
                KnowledgeHit(
                    document_id=hit.file_id,
                    document_name=hit.file_name,
                    chunk_index=hit.chunk_index,
                    content=hit.chunk_text,
                    score_distance=hit.distance,
                )
                for hit in hits
            ),
            query=query.query,
        )

    async def answer(self, query: AnswerKnowledgeQuery) -> KnowledgeAnswer:
        visible = (
            list(query.visible_knowledge_base_ids)
            if query.visible_knowledge_base_ids is not None
            else None
        )
        result = await sqlalchemy_retrieval.answer(
            self._session,
            query.query,
            top_k=query.top_k,
            user_id=query.principal_id,
            visible_kb_ids=visible,
        )
        citations = tuple(
            Citation(
                index=int(source["index"]),
                document_id=uuid.UUID(str(source["file_id"])),
                document_name=str(source["file_name"]),
                chunk_index=int(source["chunk_index"]),
                snippet=str(source.get("snippet", "")),
            )
            for source in result["sources"]
        )
        return KnowledgeAnswer(answer=str(result["answer"]), citations=citations)

    async def diagnose(self, query: SearchKnowledgeQuery) -> KnowledgeRetrievalArmDiagnostics:
        visible = (
            list(query.visible_knowledge_base_ids)
            if query.visible_knowledge_base_ids is not None
            else None
        )
        vector_hits, keyword_hits = await sqlalchemy_retrieval.diagnostic_arms(
            self._session,
            query.query,
            query.top_k,
            visible,
        )
        fused_hits = await sqlalchemy_retrieval.search(
            self._session,
            query.query,
            top_k=query.top_k,
            visible_kb_ids=visible,
        )

        def _published(hit: sqlalchemy_retrieval.Hit) -> KnowledgeHit:
            return KnowledgeHit(
                document_id=hit.file_id,
                document_name=hit.file_name,
                chunk_index=hit.chunk_index,
                content=hit.chunk_text,
                score_distance=hit.distance,
            )

        return KnowledgeRetrievalArmDiagnostics(
            vector=SearchKnowledgeResult(
                hits=tuple(_published(hit) for hit in vector_hits),
                query=query.query,
            ),
            keyword=SearchKnowledgeResult(
                hits=tuple(_published(hit) for hit in keyword_hits),
                query=query.query,
            ),
            fused=SearchKnowledgeResult(
                hits=tuple(_published(hit) for hit in fused_hits),
                query=query.query,
            ),
        )
