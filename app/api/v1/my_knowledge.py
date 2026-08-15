"""个人知识中枢接口（docs/27 阶段 B1）：本人个人库的入库 / 列出 / 检索 / 问答。

隔离铁律：owner 一律取登录用户；检索/问答只放行**本人个人库 id**（复用既有 visible_kb_ids
杠杆），路由不接受任何客户端传入的 knowledge_base_id → 跨人个人知识不可见、无从冒充。
任意登录用户管理自己的知识，无需管理员。
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.contexts.foundations.knowledge.knowledge_indexing.contracts import IndexTextCommand
from app.contexts.foundations.knowledge.knowledge_indexing.public import (
    index_text as index_text_document,
)
from app.contexts.foundations.knowledge.knowledge_indexing.public import list_documents
from app.contexts.foundations.knowledge.knowledge_retrieval.contracts import (
    AnswerKnowledgeQuery,
    SearchKnowledgeQuery,
)
from app.contexts.foundations.knowledge.knowledge_retrieval.public import (
    answer_knowledge,
    search_knowledge,
)
from app.contexts.foundations.knowledge.wiki_management.public import ensure_personal_kb
from app.platform.database import get_db
from app.platform.http_runtime import ok
from app.schemas.knowledge import AskRequest, AskResponse, FileOut, TextIngestRequest

router = APIRouter(prefix="/my-knowledge", tags=["my-knowledge"])

DB = Annotated[AsyncSession, Depends(get_db)]


async def _my_kb(db: AsyncSession, user_id: uuid.UUID) -> uuid.UUID:
    """本人个人库 id（首次自动建）——检索/入库唯一放行的库。"""
    return await ensure_personal_kb(db, user_id)


@router.post("/documents")
async def ingest_my_text(body: TextIngestRequest, db: DB, user: CurrentUser) -> dict:
    """粘贴正文入我的个人知识库（owner=登录用户）。请求体里的 knowledge_base_id 被忽略。"""
    kb_id = await _my_kb(db, user.id)
    kf = await index_text_document(
        db,
        IndexTextCommand(
            title=body.title,
            text=body.text,
            uploader_id=user.id,
            knowledge_base_id=kb_id,
            category=body.category,
        ),
    )
    return ok(FileOut.model_validate(kf).model_dump(mode="json"))


@router.get("/documents")
async def list_my_documents(
    db: DB,
    user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> dict:
    """列出我的个人知识库文档（仅本人条目，按上传时间倒序）。"""
    kb_id = await _my_kb(db, user.id)
    files = await list_documents(db, limit=limit, knowledge_base_id=kb_id)
    return ok([FileOut.model_validate(f).model_dump(mode="json") for f in files])


@router.post("/search")
async def search_my_knowledge(body: AskRequest, db: DB, user: CurrentUser) -> dict:
    """在我的个人知识库检索（仅本人库参与召回）。"""
    kb_id = await _my_kb(db, user.id)
    result = await search_knowledge(
        db,
        SearchKnowledgeQuery(
            query=body.query,
            top_k=body.top_k,
            visible_knowledge_base_ids=(kb_id,),
        ),
    )
    hits: list[dict[str, Any]] = [
        {
            "file_id": str(hit.document_id),
            "file_name": hit.document_name,
            "chunk_index": hit.chunk_index,
            "score_distance": hit.score_distance,
            "snippet": hit.content,
        }
        for hit in result.hits
    ]
    return ok({"query": body.query, "hits": hits})


@router.post("/ask")
async def ask_my_knowledge(body: AskRequest, db: DB, user: CurrentUser) -> dict:
    """个人知识问答（仅本人条目参与，带来源溯源）。"""
    kb_id = await _my_kb(db, user.id)
    result = await answer_knowledge(
        db,
        AnswerKnowledgeQuery(
            query=body.query,
            top_k=body.top_k,
            principal_id=user.id,
            visible_knowledge_base_ids=(kb_id,),
        ),
    )
    sources = [
        {
            "index": citation.index,
            "file_id": str(citation.document_id),
            "file_name": citation.document_name,
            "chunk_index": citation.chunk_index,
            "snippet": citation.snippet,
        }
        for citation in result.citations
    ]
    return ok(AskResponse(answer=result.answer, sources=sources).model_dump(mode="json"))
