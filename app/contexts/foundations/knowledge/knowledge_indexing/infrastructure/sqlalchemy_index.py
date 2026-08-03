"""SQLAlchemy indexing: source document → chunks → vectors → versioned events.

一次入库一个文档；分块向量化失败时把文件状态置 failed 并抛错，不留半索引脏数据。
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import UTC, datetime

from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.knowledge import embedding_gateway
from app.contexts.foundations.knowledge.knowledge_indexing.contracts import (
    DocumentIndexRemovedV1,
    IndexReadyV1,
)
from app.contexts.foundations.knowledge.knowledge_indexing.domain.chunking import chunk_text
from app.contexts.foundations.knowledge.knowledge_indexing.infrastructure.document_extract import (
    extract_text,
)
from app.contexts.foundations.knowledge.wiki_management.contracts import (
    DocumentArchivedV1,
    DocumentPublishedV1,
    DocumentSnapshot,
)
from app.contexts.shared_kernel import ApplicationError, ResourceNotFound, RuleViolation
from app.integrations.feishu.client import feishu_client
from app.models.knowledge import KnowledgeBase, KnowledgeFile, KnowledgeVector
from app.platform.object_storage import gateway as storage_gateway
from app.platform.outbox import repository as outbox_repository
from app.platform.outbox.source_change import publish_source_change

logger = logging.getLogger(__name__)

# Compatibility seam: existing tests/plugins patch ingest.embed_texts.
embed_texts = embedding_gateway.embed_texts


def _source_version() -> int:
    return time.time_ns()


def _document_snapshot(file: KnowledgeFile, *, source_version: int) -> DocumentSnapshot:
    return DocumentSnapshot(
        id=file.id,
        knowledge_base_id=file.knowledge_base_id,
        file_name=file.file_name,
        category=file.category,
        uploader_id=file.uploader_id,
        storage_path=file.storage_path,
        file_size=file.file_size,
        mime_type=file.mime_type,
        status=file.status,
        source_version=source_version,
    )


async def _publish_document_ready(
    db: AsyncSession,
    file: KnowledgeFile,
    *,
    chunk_count: int,
    source_version: int,
) -> None:
    occurred_at = datetime.now(UTC)
    scope = ("knowledge", f"knowledge_base:{file.knowledge_base_id}")
    published = DocumentPublishedV1(
        event_id=uuid.uuid4(),
        document=_document_snapshot(file, source_version=source_version),
        scope=scope,
        occurred_at=occurred_at,
    )
    ready = IndexReadyV1(
        event_id=uuid.uuid4(),
        document_id=file.id,
        knowledge_base_id=file.knowledge_base_id,
        index_version=source_version,
        chunk_count=chunk_count,
        scope=scope,
        occurred_at=occurred_at,
    )
    await outbox_repository.enqueue(
        db,
        event_id=published.event_id,
        aggregate_type="knowledge_document",
        aggregate_id=file.id,
        event_type=published.event_type,
        dedupe_key=f"knowledge-document:{file.id}:published:v{source_version}",
        payload={
            "event_id": str(published.event_id),
            "event_type": published.event_type,
            "document_id": str(file.id),
            "knowledge_base_id": str(file.knowledge_base_id),
            "source_version": source_version,
            "scope": list(scope),
            "occurred_at": occurred_at.isoformat(),
        },
    )
    await outbox_repository.enqueue(
        db,
        event_id=ready.event_id,
        aggregate_type="knowledge_index",
        aggregate_id=file.id,
        event_type=ready.event_type,
        dedupe_key=f"knowledge-index:{file.id}:ready:v{source_version}",
        payload={
            "event_id": str(ready.event_id),
            "event_type": ready.event_type,
            "document_id": str(file.id),
            "knowledge_base_id": str(file.knowledge_base_id),
            "index_version": source_version,
            "chunk_count": chunk_count,
            "scope": list(scope),
            "occurred_at": occurred_at.isoformat(),
        },
    )
    await publish_source_change(
        db,
        source_type="knowledge_index",
        source_id=file.id,
        source_version=source_version,
        affected_scopes=scope,
        occurred_at=occurred_at,
    )


async def _publish_document_archived(
    db: AsyncSession,
    file: KnowledgeFile,
    *,
    source_version: int,
) -> None:
    occurred_at = datetime.now(UTC)
    scope = ("knowledge", f"knowledge_base:{file.knowledge_base_id}")
    archived = DocumentArchivedV1(
        event_id=uuid.uuid4(),
        document_id=file.id,
        knowledge_base_id=file.knowledge_base_id,
        source_version=source_version,
        scope=scope,
        occurred_at=occurred_at,
    )
    removed = DocumentIndexRemovedV1(
        event_id=uuid.uuid4(),
        document_id=file.id,
        index_version=source_version,
        occurred_at=occurred_at,
    )
    for event, event_type, aggregate_type, dedupe_key in (
        (
            archived,
            archived.event_type,
            "knowledge_document",
            f"knowledge-document:{file.id}:archived:v{source_version}",
        ),
        (
            removed,
            removed.event_type,
            "knowledge_index",
            f"knowledge-index:{file.id}:removed:v{source_version}",
        ),
    ):
        await outbox_repository.enqueue(
            db,
            event_id=event.event_id,
            aggregate_type=aggregate_type,
            aggregate_id=file.id,
            event_type=event_type,
            dedupe_key=dedupe_key,
            payload={
                "event_id": str(event.event_id),
                "event_type": event_type,
                "document_id": str(file.id),
                "knowledge_base_id": str(file.knowledge_base_id),
                "source_version": source_version,
                "scope": list(scope),
                "occurred_at": occurred_at.isoformat(),
            },
        )
    await publish_source_change(
        db,
        source_type="knowledge_index",
        source_id=file.id,
        source_version=source_version,
        affected_scopes=scope,
        occurred_at=occurred_at,
    )


async def _index_text(
    db: AsyncSession,
    file: KnowledgeFile,
    text: str,
    *,
    publish_events: bool = True,
) -> KnowledgeFile:
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
        if publish_events:
            source_version = _source_version()
            await _publish_document_ready(
                db,
                file,
                chunk_count=len(chunks),
                source_version=source_version,
            )
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
    file.storage_path = await storage_gateway.put_object(
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
    publish_events: bool = True,
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
    return await _index_text(db, file, text, publish_events=publish_events)


async def ingest_feishu_doc(
    db: AsyncSession,
    *,
    document_id: str,
    uploader_id: uuid.UUID,
    knowledge_base_id: uuid.UUID,
    category: str | None = None,
) -> KnowledgeFile:
    """拉取飞书云文档纯文本入库（复用 FeishuClient.get_document_raw_content）。"""
    text = await feishu_client.get_document_raw_content(document_id)
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
    await _publish_document_archived(db, file, source_version=_source_version())
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
    await _publish_document_ready(
        db,
        file,
        chunk_count=0,
        source_version=_source_version(),
    )
    await db.commit()
    await db.refresh(file)
    return file
