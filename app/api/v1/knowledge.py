"""知识库接口：上传/粘贴/飞书入库 + 列表/删除 + 问答。

写操作（入库/删除）需 admin/executive；读操作（列表/问答）任意登录用户。
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, require_roles
from app.contexts.foundations.access_control.entrypoints.operations import (
    visible_knowledge_ids,
)
from app.contexts.foundations.governance.audit_trail.public import (
    AppendAuditRecordCommand,
    append_audit_record,
)
from app.contexts.foundations.identity.contracts import Principal, PrincipalType
from app.contexts.foundations.knowledge.knowledge_indexing.contracts import (
    IndexFeishuDocumentCommand,
    IndexFileCommand,
    IndexTextCommand,
)
from app.contexts.foundations.knowledge.knowledge_indexing.public import (
    index_feishu_document,
    index_file,
    list_documents,
    move_document,
    remove_document_index,
)
from app.contexts.foundations.knowledge.knowledge_indexing.public import (
    index_text as index_text_document,
)
from app.contexts.foundations.knowledge.knowledge_retrieval.contracts import (
    AnswerKnowledgeQuery,
)
from app.contexts.foundations.knowledge.knowledge_retrieval.public import (
    answer_knowledge,
)
from app.contexts.foundations.knowledge.wiki_management.public import (
    get_default_knowledge_base,
    get_knowledge_base,
)
from app.contexts.shared_kernel import RuleViolation
from app.core.database import get_db
from app.platform.http_runtime import ok
from app.schemas.knowledge import (
    AskRequest,
    AskResponse,
    FeishuIngestRequest,
    FileOut,
    TextIngestRequest,
)

router = APIRouter(prefix="/knowledge", tags=["knowledge"])

DB = Annotated[AsyncSession, Depends(get_db)]
Manager = Annotated[Any, Depends(require_roles("admin", "executive"))]

_MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20MB 上限，防大文件读入内存 OOM（nginx 另有 50m 兜底）


async def _resolve_kb_id(db: AsyncSession, provided: uuid.UUID | None) -> uuid.UUID:
    """缺省落公司公共库；显式传入则校验存在（不存在→404，避免 FK 违例 500）。"""
    if provided is None:
        return (await get_default_knowledge_base(db)).id
    return (await get_knowledge_base(db, provided)).id


@router.post("/files")
async def upload_file(
    db: DB,
    manager: Manager,
    file: Annotated[UploadFile, File()],
    category: Annotated[str | None, Form()] = None,
    knowledge_base_id: Annotated[uuid.UUID | None, Form()] = None,
) -> dict:
    """上传文件入库（支持 txt/md/docx/pdf，单文件 ≤20MB）。缺省入公司公共库。"""
    if file.size is not None and file.size > _MAX_UPLOAD_BYTES:
        raise RuleViolation(
            f"文件过大（>{_MAX_UPLOAD_BYTES // 1024 // 1024}MB），请压缩或拆分后上传"
        )
    content = await file.read()
    if len(content) > _MAX_UPLOAD_BYTES:  # Content-Length 缺失/不实时兜底
        raise RuleViolation(
            f"文件过大（>{_MAX_UPLOAD_BYTES // 1024 // 1024}MB），请压缩或拆分后上传"
        )
    kb_id = await _resolve_kb_id(db, knowledge_base_id)
    kf = await index_file(
        db,
        IndexFileCommand(
            file_name=file.filename or "未命名",
            content=content,
            mime_type=file.content_type,
            uploader_id=manager.id,
            knowledge_base_id=kb_id,
            category=category,
        ),
    )
    return ok(FileOut.model_validate(kf).model_dump(mode="json"))


@router.post("/text")
async def ingest_text(body: TextIngestRequest, db: DB, manager: Manager) -> dict:
    """粘贴正文入库。缺省入公司公共库。"""
    kb_id = await _resolve_kb_id(db, body.knowledge_base_id)
    kf = await index_text_document(
        db,
        IndexTextCommand(
            title=body.title,
            text=body.text,
            uploader_id=manager.id,
            knowledge_base_id=kb_id,
            category=body.category,
        ),
    )
    return ok(FileOut.model_validate(kf).model_dump(mode="json"))


@router.post("/feishu")
async def ingest_feishu(body: FeishuIngestRequest, db: DB, manager: Manager) -> dict:
    """拉取飞书云文档入库。缺省入公司公共库。"""
    kb_id = await _resolve_kb_id(db, body.knowledge_base_id)
    kf = await index_feishu_document(
        db,
        IndexFeishuDocumentCommand(
            document_id=body.document_id,
            uploader_id=manager.id,
            knowledge_base_id=kb_id,
            category=body.category,
        ),
    )
    return ok(FileOut.model_validate(kf).model_dump(mode="json"))


@router.get("/files")
async def list_files(
    db: DB,
    _: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> dict:
    """文档列表（未删除，按上传时间倒序，默认最多 100 条）。"""
    files = await list_documents(db, limit=limit)
    return ok([FileOut.model_validate(f).model_dump(mode="json") for f in files])


@router.delete("/files/{file_id}")
async def delete_file(file_id: uuid.UUID, db: DB, _: Manager) -> dict:
    """删除文档（软删文件 + 回收其向量）。"""
    await remove_document_index(db, file_id)
    return ok()


class MoveFileRequest(BaseModel):
    """把文档移到另一个知识库。"""

    knowledge_base_id: uuid.UUID


@router.patch("/files/{file_id}/move")
async def move_file(file_id: uuid.UUID, body: MoveFileRequest, db: DB, _: Manager) -> dict:
    """把文档移到另一个知识库（改归属库）。"""
    kf = await move_document(db, file_id, body.knowledge_base_id)
    return ok(FileOut.model_validate(kf).model_dump(mode="json"))


@router.post("/ask")
async def ask(body: AskRequest, db: DB, user: CurrentUser) -> dict:
    """知识库问答（带来源溯源）。按请求用户可见范围隔离检索（契约② scope ∪ grant）。"""
    principal = Principal(
        principal_type=PrincipalType.USER,
        principal_id=user.id,
        role_code=user.role_code,
        department_id=user.department_id,
        is_active=user.is_active,
    )
    ids = await visible_knowledge_ids(db, principal=principal)
    # 红线监督（决策⑥）：admin 全库可见=跨部门检索，每次落审计
    if user.role_code == "admin":
        await append_audit_record(
            db,
            AppendAuditRecordCommand(
                actor_id=user.id,
                actor_role=user.role_code,
                action="knowledge.cross_dept_search",
                summary=f"跨部门检索：{body.query[:60]}",
            )
        )
    result = await answer_knowledge(
        db,
        AnswerKnowledgeQuery(
            query=body.query,
            top_k=body.top_k,
            principal_id=user.id,
            visible_knowledge_base_ids=tuple(ids),
        ),
    )
    sources = [
        {
            "index": citation.index,
            "file_id": str(citation.document_id),
            "file_name": citation.document_name,
            "chunk_index": citation.chunk_index,
        }
        for citation in result.citations
    ]
    return ok(AskResponse(answer=result.answer, sources=sources).model_dump(mode="json"))
