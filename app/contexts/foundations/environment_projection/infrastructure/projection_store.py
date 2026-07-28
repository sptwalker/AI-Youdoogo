"""Persistence and published-Knowledge adapters for Environment Projection."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.environment_projection.contracts.context_snapshot import (
    SnapshotProvenance,
    SnapshotSourceVersion,
)
from app.contexts.foundations.environment_projection.contracts.source_change import (
    EnvironmentSourceChange,
)
from app.contexts.foundations.identity import public as identity
from app.contexts.foundations.knowledge.knowledge_indexing.contracts import (
    IndexedDocument,
    IndexTextCommand,
)
from app.contexts.foundations.knowledge.knowledge_indexing.public import (
    build_local_knowledge_index_port,
)
from app.contexts.foundations.knowledge.wiki_management.public import (
    get_default_knowledge_base,
)
from app.platform.outbox.model import OutboxEvent
from app.platform.outbox.source_change import (
    DEFAULT_TENANT_ID,
    ENVIRONMENT_SOURCE_CHANGED_V1,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ArchiveTarget:
    knowledge_base_id: uuid.UUID
    uploader_id: uuid.UUID


async def prepare_archive_target(session: AsyncSession) -> ArchiveTarget | None:
    knowledge_base = await get_default_knowledge_base(session)
    users = await identity.list_users(session)
    admin = next((user for user in users if user.role_code == "admin"), None)
    if admin is None:
        return None
    return ArchiveTarget(
        knowledge_base_id=knowledge_base.id,
        uploader_id=admin.id,
    )


async def replace_archived_snapshot(
    session: AsyncSession,
    *,
    target: ArchiveTarget,
    title: str,
    category: str,
    text: str,
) -> None:
    index = build_local_knowledge_index_port(session)
    documents = await _all_documents(session)
    existing = sorted(
        (
            document
            for document in documents
            if document.file_name == title
            and document.knowledge_base_id == target.knowledge_base_id
        ),
        key=lambda document: document.create_time,
    )
    for document in existing:
        await index.remove_document_index(document.id)
    await index.index_text(
        IndexTextCommand(
            title=title,
            text=text,
            uploader_id=target.uploader_id,
            knowledge_base_id=target.knowledge_base_id,
            category=category,
            publish_events=False,
        ),
    )


async def load_snapshot_source_metadata(
    session: AsyncSession,
) -> tuple[tuple[SnapshotProvenance, ...], tuple[SnapshotSourceVersion, ...]]:
    events = list(
        (
            await session.execute(
                select(OutboxEvent)
                .where(OutboxEvent.event_type == ENVIRONMENT_SOURCE_CHANGED_V1)
                .order_by(OutboxEvent.create_time, OutboxEvent.id)
            )
        ).scalars()
    )
    newest: dict[tuple[str, uuid.UUID], tuple[EnvironmentSourceChange, uuid.UUID]] = {}
    for event in events:
        try:
            change = EnvironmentSourceChange.from_wire(
                event_id=event.id,
                event_type=event.event_type,
                payload=event.payload,
            )
        except (TypeError, ValueError):
            logger.warning(
                "忽略无效的环境来源事件 event_id=%s",
                event.id,
                exc_info=True,
            )
            continue
        if change.tenant_id != DEFAULT_TENANT_ID:
            continue
        key = (change.source_type, change.source_id)
        current = newest.get(key)
        if current is None or change.source_version > current[0].source_version:
            newest[key] = (change, event.id)

    ordered = sorted(
        newest.values(),
        key=lambda item: (item[0].source_type, str(item[0].source_id)),
    )
    provenance = tuple(
        SnapshotProvenance(
            event_id=event_id,
            source_type=change.source_type,
            source_id=change.source_id,
            observed_at=change.occurred_at,
        )
        for change, event_id in ordered
    )
    versions = tuple(
        SnapshotSourceVersion(
            source_type=change.source_type,
            source_id=change.source_id,
            version=change.source_version,
        )
        for change, _event_id in ordered
    )
    return provenance, versions


async def _all_documents(session: AsyncSession) -> tuple[IndexedDocument, ...]:
    index = build_local_knowledge_index_port(session)
    limit = 100
    while True:
        documents = await index.list_documents(limit=limit)
        if len(documents) < limit:
            return documents
        limit *= 2
