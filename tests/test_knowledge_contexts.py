"""Fast contract and application tests for the five Knowledge contexts."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import TracebackType

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.contexts.foundations.knowledge.knowledge_indexing.application.use_cases import (
    KnowledgeIndexing,
)
from app.contexts.foundations.knowledge.knowledge_indexing.contracts import (
    DocumentIndexRemovedV1,
    IndexedDocument,
    IndexReadyV1,
    IndexTextCommand,
)
from app.contexts.foundations.knowledge.knowledge_indexing.infrastructure import (
    event_handler,
)
from app.contexts.foundations.knowledge.knowledge_retrieval.application.use_cases import (
    KnowledgeRetrieval,
)
from app.contexts.foundations.knowledge.knowledge_retrieval.contracts import (
    AnswerKnowledgeQuery,
    KnowledgeAnswer,
    SearchKnowledgeQuery,
    SearchKnowledgeResult,
)
from app.contexts.foundations.knowledge.organizational_memory.application.use_cases import (
    OrganizationalMemory,
)
from app.contexts.foundations.knowledge.organizational_memory.contracts import (
    DistillConversationCommand,
    MemoryDraft,
)
from app.contexts.foundations.knowledge.semantic_catalog.domain.models import (
    SemanticTerm,
    expand_terms,
    render_term_prompt,
)
from app.contexts.foundations.knowledge.wiki_management.application.contracts import (
    CreateKnowledgeBase,
)
from app.contexts.foundations.knowledge.wiki_management.application.ports import (
    KnowledgeBaseRepository,
    KnowledgeChangePublisher,
)
from app.contexts.foundations.knowledge.wiki_management.application.use_cases import (
    WikiManagement,
)
from app.contexts.foundations.knowledge.wiki_management.contracts import (
    DocumentArchivedV1,
    DocumentPublishedV1,
    DocumentSnapshot,
    KnowledgeScope,
)
from app.contexts.foundations.knowledge.wiki_management.domain.models import KnowledgeBase
from app.contexts.shared_kernel import RuleViolation
from app.knowledge import ingest
from app.models import Base
from app.models.knowledge import KnowledgeBase as KnowledgeBaseRow
from app.models.system import SysUser
from app.platform.outbox.model import OutboxEvent


class FakeWikiRepository:
    def __init__(self) -> None:
        self.records: dict[uuid.UUID, KnowledgeBase] = {}

    async def get(self, knowledge_base_id: uuid.UUID) -> KnowledgeBase | None:
        return self.records.get(knowledge_base_id)

    async def get_default(self) -> KnowledgeBase | None:
        return next((record for record in self.records.values() if record.is_default), None)

    async def code_exists(self, code: str, *, excluding_id: uuid.UUID | None = None) -> bool:
        return any(
            record.code == code and record.id != excluding_id for record in self.records.values()
        )

    async def document_count(self, knowledge_base_id: uuid.UUID) -> int:
        return 0

    async def list_records(self) -> tuple[tuple[KnowledgeBase, int], ...]:
        return tuple((record, 0) for record in self.records.values())

    async def add(self, knowledge_base: KnowledgeBase) -> None:
        self.records[knowledge_base.id] = knowledge_base

    async def save(self, knowledge_base: KnowledgeBase) -> None:
        self.records[knowledge_base.id] = knowledge_base

    async def soft_delete(self, knowledge_base_id: uuid.UUID) -> None:
        self.records.pop(knowledge_base_id)


class FakeKnowledgePublisher:
    def __init__(self) -> None:
        self.ids: list[uuid.UUID] = []

    async def publish(self, knowledge_base: KnowledgeBase) -> None:
        self.ids.append(knowledge_base.id)


class FakeWikiUnitOfWork:
    def __init__(self) -> None:
        self.repository = FakeWikiRepository()
        self.publisher = FakeKnowledgePublisher()
        self.knowledge_bases: KnowledgeBaseRepository = self.repository
        self.changes: KnowledgeChangePublisher = self.publisher
        self.commits = 0
        self.rollbacks = 0

    async def __aenter__(self) -> FakeWikiUnitOfWork:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if exc_type is not None:
            self.rollbacks += 1

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


async def test_wiki_create_owns_validation_event_and_commit() -> None:
    uow = FakeWikiUnitOfWork()
    result = await WikiManagement(lambda: uow).create(
        CreateKnowledgeBase(
            name="运营知识",
            scope=KnowledgeScope.DEPARTMENT,
            department_id=uuid.uuid4(),
        )
    )
    assert result.id in uow.repository.records
    assert uow.publisher.ids == [result.id]
    assert uow.commits == 1


def test_wiki_domain_rejects_missing_scope_owner() -> None:
    record = KnowledgeBase(
        id=uuid.uuid4(),
        name="个人记忆",
        code="personal",
        scope=KnowledgeScope.PERSONAL,
    )
    with pytest.raises(RuleViolation, match="智能体"):
        record.validate()


def test_semantic_catalog_policy_is_pure_and_bounded() -> None:
    terms = [
        SemanticTerm(
            id=uuid.uuid4(),
            canonical_name="累计激活设备数",
            aliases=("激活量", "新增设备"),
            definition="new_device 去重",
        )
    ]
    assert expand_terms("查激活量", terms) == ("累计激活设备数", "新增设备")
    assert "new_device 去重" in render_term_prompt(terms)


class FakeIndexGateway:
    def __init__(self, result: IndexedDocument) -> None:
        self.result = result
        self.commands: list[IndexTextCommand] = []

    async def index_text(self, command: IndexTextCommand) -> IndexedDocument:
        self.commands.append(command)
        return self.result

    async def index_file(self, command: object) -> IndexedDocument:
        return self.result

    async def index_feishu_document(self, command: object) -> IndexedDocument:
        return self.result

    async def remove(self, document_id: uuid.UUID) -> None:
        return None

    async def move(self, document_id: uuid.UUID, knowledge_base_id: uuid.UUID) -> IndexedDocument:
        return self.result


async def test_indexing_use_case_delegates_plain_command() -> None:
    now = datetime.now(UTC)
    document = IndexedDocument(
        id=uuid.uuid4(),
        file_name="sop.md",
        knowledge_base_id=uuid.uuid4(),
        category="sop",
        uploader_id=uuid.uuid4(),
        storage_path="inline",
        file_size=12,
        mime_type="text/plain",
        status="indexed",
        create_time=now,
    )
    gateway = FakeIndexGateway(document)
    command = IndexTextCommand(
        title="sop.md",
        text="步骤",
        uploader_id=document.uploader_id,
        knowledge_base_id=document.knowledge_base_id,
    )
    assert await KnowledgeIndexing(gateway).index_text(command) == document
    assert gateway.commands == [command]


class FailingRetrievalGateway:
    async def search(self, query: SearchKnowledgeQuery) -> SearchKnowledgeResult:
        raise AssertionError("blank query must not reach gateway")

    async def answer(self, query: AnswerKnowledgeQuery) -> KnowledgeAnswer:
        raise AssertionError("blank query must not reach gateway")


async def test_retrieval_rejects_blank_query_without_infrastructure() -> None:
    retrieval = KnowledgeRetrieval(FailingRetrievalGateway())
    assert (await retrieval.search(SearchKnowledgeQuery(query="  "))).hits == ()
    answer = await retrieval.answer(AnswerKnowledgeQuery(query=""))
    assert answer.citations == () and "资料不足" in answer.answer


class FailingMemoryPort:
    async def distill(self, command: DistillConversationCommand) -> MemoryDraft | None:
        raise RuntimeError("provider unavailable")


async def test_memory_failure_preserves_archive_fallback_contract() -> None:
    memory = OrganizationalMemory(FailingMemoryPort())
    assert await memory.distill(DistillConversationCommand(transcript="原始对话")) is None


def test_document_and_index_events_are_versioned_pure_data() -> None:
    now = datetime.now(UTC)
    document = DocumentSnapshot(
        id=uuid.uuid4(),
        knowledge_base_id=uuid.uuid4(),
        file_name="制度.md",
        category="policy",
        uploader_id=uuid.uuid4(),
        storage_path="inline",
        file_size=10,
        mime_type="text/plain",
        status="indexed",
        source_version=7,
    )
    published = DocumentPublishedV1(uuid.uuid4(), document, ("knowledge",), now)
    archived = DocumentArchivedV1(
        uuid.uuid4(), document.id, document.knowledge_base_id, 8, ("knowledge",), now
    )
    ready = IndexReadyV1(
        uuid.uuid4(), document.id, document.knowledge_base_id, 7, 2, ("knowledge",), now
    )
    removed = DocumentIndexRemovedV1(uuid.uuid4(), document.id, 8, now)
    assert published.event_type.endswith(".v1")
    assert archived.source_version == removed.index_version == 8
    assert ready.chunk_count == 2


async def test_knowledge_event_handler_validates_versioned_identity() -> None:
    class Event:
        event_type = "knowledge.index.ready.v1"
        payload = {
            "event_id": str(uuid.uuid4()),
            "document_id": str(uuid.uuid4()),
            "index_version": 3,
        }

    await event_handler.handle(Event())


async def test_indexing_publishes_document_index_and_projection_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        user = SysUser(id=uuid.uuid4(), username="knowledge-owner", password_hash="x")
        knowledge_base = KnowledgeBaseRow(
            id=uuid.uuid4(), name="制度库", code="policy", scope="company"
        )
        session.add_all([user, knowledge_base])
        await session.commit()

        async def fake_embeddings(chunks: list[str]) -> list[list[float]]:
            return [[0.0] * 1024 for _ in chunks]

        monkeypatch.setattr(ingest, "embed_texts", fake_embeddings)
        document = await ingest.ingest_text(
            session,
            title="制度.md",
            text="审批制度",
            uploader_id=user.id,
            knowledge_base_id=knowledge_base.id,
        )
        event_types = set((await session.execute(select(OutboxEvent.event_type))).scalars())
        assert {
            "knowledge.document.published.v1",
            "knowledge.index.ready.v1",
            "environment.source.changed.v1",
        }.issubset(event_types)

        await ingest.delete_file(session, document.id)
        event_types = set((await session.execute(select(OutboxEvent.event_type))).scalars())
        assert {
            "knowledge.document.archived.v1",
            "knowledge.index.removed.v1",
        }.issubset(event_types)
    await engine.dispose()
