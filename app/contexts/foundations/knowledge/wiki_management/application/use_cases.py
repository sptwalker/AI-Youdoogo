"""Wiki Management application orchestration."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from app.contexts.foundations.knowledge.wiki_management.application.contracts import (
    CreateKnowledgeBase,
    UpdateKnowledgeBase,
)
from app.contexts.foundations.knowledge.wiki_management.application.ports import WikiUnitOfWork
from app.contexts.foundations.knowledge.wiki_management.contracts import KnowledgeBaseSnapshot
from app.contexts.foundations.knowledge.wiki_management.domain.models import KnowledgeBase
from app.contexts.shared_kernel import ConflictDetected, ResourceNotFound, RuleViolation

UowFactory = Callable[[], WikiUnitOfWork]


def _snapshot(record: KnowledgeBase, *, file_count: int = 0) -> KnowledgeBaseSnapshot:
    return KnowledgeBaseSnapshot(
        id=record.id,
        name=record.name,
        code=record.code,
        scope=record.scope,
        department_id=record.department_id,
        owner_agent_id=record.owner_agent_id,
        is_confidential=record.is_confidential,
        is_default=record.is_default,
        is_active=record.is_active,
        description=record.description,
        file_count=file_count,
    )


class WikiManagement:
    def __init__(self, uow_factory: UowFactory) -> None:
        self._uow_factory = uow_factory

    async def get(self, knowledge_base_id: uuid.UUID) -> KnowledgeBaseSnapshot:
        async with self._uow_factory() as uow:
            record = await uow.knowledge_bases.get(knowledge_base_id)
            if record is None:
                raise ResourceNotFound("知识库不存在")
            return _snapshot(record, file_count=await uow.knowledge_bases.document_count(record.id))

    async def get_default(self) -> KnowledgeBaseSnapshot:
        async with self._uow_factory() as uow:
            record = await uow.knowledge_bases.get_default()
            if record is None:
                raise RuleViolation("未找到公司公共知识库，请先执行数据库迁移")
            return _snapshot(record, file_count=await uow.knowledge_bases.document_count(record.id))

    async def list(self) -> tuple[KnowledgeBaseSnapshot, ...]:
        async with self._uow_factory() as uow:
            records = await uow.knowledge_bases.list_records()
            return tuple(_snapshot(record, file_count=count) for record, count in records)

    async def create(self, command: CreateKnowledgeBase) -> KnowledgeBaseSnapshot:
        record = KnowledgeBase(
            id=uuid.uuid4(),
            name=command.name,
            code=command.code or f"kb_{uuid.uuid4().hex[:8]}",
            scope=command.scope,
            department_id=command.department_id if command.scope.value == "department" else None,
            owner_agent_id=command.owner_agent_id if command.scope.value == "personal" else None,
            is_confidential=command.is_confidential,
            description=command.description,
        )
        record.validate()
        async with self._uow_factory() as uow:
            if await uow.knowledge_bases.code_exists(record.code):
                raise ConflictDetected("知识库编码已存在")
            await uow.knowledge_bases.add(record)
            await uow.changes.publish(record)
            await uow.commit()
        return _snapshot(record)

    async def update(self, command: UpdateKnowledgeBase) -> KnowledgeBaseSnapshot:
        async with self._uow_factory() as uow:
            record = await uow.knowledge_bases.get(command.knowledge_base_id)
            if record is None:
                raise ResourceNotFound("知识库不存在")
            record.apply_update(
                name=command.name,
                is_confidential=command.is_confidential,
                description=command.description,
                is_active=command.is_active,
                department_id=command.department_id,
            )
            await uow.knowledge_bases.save(record)
            await uow.changes.publish(record)
            await uow.commit()
            return _snapshot(record, file_count=await uow.knowledge_bases.document_count(record.id))

    async def delete(self, knowledge_base_id: uuid.UUID) -> None:
        async with self._uow_factory() as uow:
            record = await uow.knowledge_bases.get(knowledge_base_id)
            if record is None:
                raise ResourceNotFound("知识库不存在")
            record.ensure_deletable(
                document_count=await uow.knowledge_bases.document_count(knowledge_base_id)
            )
            await uow.knowledge_bases.soft_delete(knowledge_base_id)
            await uow.changes.publish(record)
            await uow.commit()
