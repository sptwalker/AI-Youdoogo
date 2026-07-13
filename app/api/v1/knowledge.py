"""知识库接口：上传/粘贴/飞书入库 + 列表/删除 + 问答。

写操作（入库/删除）需 admin/executive；读操作（列表/问答）任意登录用户。
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, require_roles
from app.core.database import get_db
from app.core.exceptions import AppError, ok
from app.knowledge import ingest, retrieval
from app.models.knowledge import KnowledgeFile
from app.models.system import SysUser
from app.schemas.knowledge import (
    AskRequest,
    AskResponse,
    FeishuIngestRequest,
    FileOut,
    TextIngestRequest,
)

router = APIRouter(prefix="/knowledge", tags=["knowledge"])

DB = Annotated[AsyncSession, Depends(get_db)]
Manager = Annotated[SysUser, Depends(require_roles("admin", "executive"))]

_MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20MB 上限，防大文件读入内存 OOM（nginx 另有 50m 兜底）


@router.post("/files")
async def upload_file(
    db: DB,
    manager: Manager,
    file: Annotated[UploadFile, File()],
    category: Annotated[str | None, Form()] = None,
) -> dict:
    """上传文件入库（支持 txt/md/docx/pdf，单文件 ≤20MB）。"""
    if file.size is not None and file.size > _MAX_UPLOAD_BYTES:
        raise AppError(f"文件过大（>{_MAX_UPLOAD_BYTES // 1024 // 1024}MB），请压缩或拆分后上传")
    content = await file.read()
    if len(content) > _MAX_UPLOAD_BYTES:  # Content-Length 缺失/不实时兜底
        raise AppError(f"文件过大（>{_MAX_UPLOAD_BYTES // 1024 // 1024}MB），请压缩或拆分后上传")
    kf = await ingest.ingest_file(
        db,
        file_name=file.filename or "未命名",
        content=content,
        mime_type=file.content_type,
        uploader_id=manager.id,
        category=category,
    )
    return ok(FileOut.model_validate(kf).model_dump(mode="json"))


@router.post("/text")
async def ingest_text(body: TextIngestRequest, db: DB, manager: Manager) -> dict:
    """粘贴正文入库。"""
    kf = await ingest.ingest_text(
        db, title=body.title, text=body.text, uploader_id=manager.id, category=body.category
    )
    return ok(FileOut.model_validate(kf).model_dump(mode="json"))


@router.post("/feishu")
async def ingest_feishu(body: FeishuIngestRequest, db: DB, manager: Manager) -> dict:
    """拉取飞书云文档入库。"""
    kf = await ingest.ingest_feishu_doc(
        db, document_id=body.document_id, uploader_id=manager.id, category=body.category
    )
    return ok(FileOut.model_validate(kf).model_dump(mode="json"))


@router.get("/files")
async def list_files(
    db: DB,
    _: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> dict:
    """文档列表（未删除，按上传时间倒序，默认最多 100 条）。"""
    stmt = (
        select(KnowledgeFile)
        .where(KnowledgeFile.is_delete.is_(False))
        .order_by(KnowledgeFile.create_time.desc())
        .limit(limit)
    )
    files = list((await db.execute(stmt)).scalars())
    return ok([FileOut.model_validate(f).model_dump(mode="json") for f in files])


@router.delete("/files/{file_id}")
async def delete_file(file_id: uuid.UUID, db: DB, _: Manager) -> dict:
    """删除文档（软删文件 + 回收其向量）。"""
    await ingest.delete_file(db, file_id)
    return ok()


@router.post("/ask")
async def ask(body: AskRequest, db: DB, user: CurrentUser) -> dict:
    """知识库问答（带来源溯源）。"""
    result = await retrieval.answer(db, body.query, body.top_k, user_id=user.id)
    return ok(AskResponse(**result).model_dump(mode="json"))
