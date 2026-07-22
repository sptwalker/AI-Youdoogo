"""入库编排：文件/粘贴/飞书文档 → 抽取 → 分块 → 向量化 → 落 knowledge_vector。

一次入库一个文档；分块向量化失败时把文件状态置 failed 并抛错，不留半索引脏数据。
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.shared_kernel import ApplicationError, ResourceNotFound, RuleViolation
from app.integrations.feishu.client import FeishuClient
from app.knowledge import storage
from app.knowledge.chunk import chunk_text
from app.knowledge.embedding import embed_texts
from app.knowledge.extract import extract_text
from app.models.knowledge import KnowledgeBase, KnowledgeFile, KnowledgeVector

logger = logging.getLogger(__name__)


async def _index_text(db: AsyncSession, file: KnowledgeFile, text: str) -> KnowledgeFile:
    """对已持久化的 file 记录，把 text 分块向量化并写入向量表。"""
    file.status = "parsing"
    await db.commit()
    try:
        chunks = chunk_text(text)
        if not chunks:
            raise RuleViolation("文档内容为空，无可索引文本")
        vectors = await embed_texts(chunks)
        db.add_all(
            KnowledgeVector(
                file_id=file.id,
                chunk_index=i,
                chunk_text=chunk,
                embedding=vec,
                source_ref={"chunk_index": i},
            )
            for i, (chunk, vec) in enumerate(zip(chunks, vectors, strict=True))
        )
        file.status = "indexed"
        await db.commit()
        await db.refresh(file)
        return file
    except Exception as exc:
        await db.rollback()
        file.status = "failed"
        await db.commit()
        if isinstance(exc, ApplicationError):
            raise
        logger.exception("知识库入库失败 file_id=%s", file.id)
        raise RuleViolation("文档索引失败，请稍后重试或联系管理员") from exc


async def ingest_file(
    db: AsyncSession,
    *,
    file_name: str,
    content: bytes,
    mime_type: str | None,
    uploader_id: uuid.UUID,
    knowledge_base_id: uuid.UUID,
    category: str | None = None,
) -> KnowledgeFile:
    """上传文件入库：先抽取校验，再存 MinIO，最后分块向量化。归属指定知识库。"""
    text = extract_text(content, mime_type, file_name)  # 先校验格式，避免存了无法解析的垃圾
    file = KnowledgeFile(
        file_name=file_name,
        knowledge_base_id=knowledge_base_id,
        category=category,
        uploader_id=uploader_id,
        storage_path="",
        file_size=len(content),
        mime_type=mime_type,
        status="uploaded",
    )
    db.add(file)
    await db.commit()
    await db.refresh(file)
    file.storage_path = await storage.put_object(
        f"{file.id}/{file_name}", content, mime_type or "application/octet-stream"
    )
    return await _index_text(db, file, text)


async def ingest_text(
    db: AsyncSession,
    *,
    title: str,
    text: str,
    uploader_id: uuid.UUID,
    knowledge_base_id: uuid.UUID,
    category: str | None = None,
    file_id: uuid.UUID | None = None,
) -> KnowledgeFile:
    """粘贴正文入库；传 file_id 时可安全重放同一个逻辑文档。"""
    file = await db.get(KnowledgeFile, file_id) if file_id is not None else None
    if file is None:
        file = KnowledgeFile(
            id=file_id or uuid.uuid4(),
            file_name=title,
            knowledge_base_id=knowledge_base_id,
            category=category,
            uploader_id=uploader_id,
            storage_path="inline",
            file_size=len(text.encode("utf-8")),
            mime_type="text/plain",
            status="uploaded",
        )
        db.add(file)
        try:
            await db.commit()
        except IntegrityError:
            if file_id is None:
                raise
            # 同一确定性 ID 被另一个 worker 先创建：转为读取并继续幂等恢复。
            await db.rollback()
            file = await db.get(KnowledgeFile, file_id)
            if file is None:
                raise
        await db.refresh(file)
    else:
        file.file_name = title
        file.knowledge_base_id = knowledge_base_id
        file.category = category
        file.uploader_id = uploader_id
        file.storage_path = "inline"
        file.file_size = len(text.encode("utf-8"))
        file.mime_type = "text/plain"
        file.is_delete = False

    if file.status == "indexed":
        await db.commit()
        return file

    # uploaded/parsing/failed 表示上一次可能在任意阶段中断；清理旧分块后从头恢复。
    await db.execute(delete(KnowledgeVector).where(KnowledgeVector.file_id == file.id))
    file.status = "uploaded"
    await db.commit()
    return await _index_text(db, file, text)


async def ingest_feishu_doc(
    db: AsyncSession,
    *,
    document_id: str,
    uploader_id: uuid.UUID,
    knowledge_base_id: uuid.UUID,
    category: str | None = None,
) -> KnowledgeFile:
    """拉取飞书云文档纯文本入库（复用 FeishuClient.get_document_raw_content）。"""
    text = await FeishuClient().get_document_raw_content(document_id)
    return await ingest_text(
        db,
        title=f"飞书文档 {document_id}",
        text=text,
        uploader_id=uploader_id,
        knowledge_base_id=knowledge_base_id,
        category=category,
    )


async def delete_file(db: AsyncSession, file_id: uuid.UUID) -> None:
    """软删文件 + 硬删其向量（向量无独立价值，删文件即回收）。"""
    file = await db.get(KnowledgeFile, file_id)
    if file is None or file.is_delete:
        raise ResourceNotFound("文档不存在")
    await db.execute(delete(KnowledgeVector).where(KnowledgeVector.file_id == file_id))
    file.is_delete = True
    await db.commit()


async def move_file(
    db: AsyncSession, file_id: uuid.UUID, knowledge_base_id: uuid.UUID
) -> KnowledgeFile:
    """把文档移到另一个知识库（改归属库）。向量按 file_id 关联，无需动。"""
    file = await db.get(KnowledgeFile, file_id)
    if file is None or file.is_delete:
        raise ResourceNotFound("文档不存在")
    kb = await db.get(KnowledgeBase, knowledge_base_id)
    if kb is None or kb.is_delete:
        raise ResourceNotFound("目标知识库不存在")
    file.knowledge_base_id = knowledge_base_id
    await db.commit()
    await db.refresh(file)
    return file
