"""B1.3 个人经验自动沉淀 单测（docs/27 阶段 B，离线）：沉淀 handler 落个人库 + enqueue 幂等。

handler 只验「构造正确的 index_text 命令 + 落到产出人个人库」（index_text 内部别处已测，mock 之）；
enqueue 验同一产出记录只登记一次（dedupe_key）。
"""

import uuid
from collections.abc import AsyncGenerator
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.contexts.foundations.knowledge.knowledge_indexing.contracts import IndexTextCommand
from app.contexts.foundations.knowledge.knowledge_indexing.infrastructure import personal_sink
from app.models import Base
from app.models.knowledge import KnowledgeBase
from app.platform.outbox.model import OutboxEvent


@pytest.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


class _FakePort:
    def __init__(self) -> None:
        self.captured: IndexTextCommand | None = None

    async def index_text(self, command: IndexTextCommand) -> object:
        self.captured = command
        return SimpleNamespace(id=command.document_id)


async def test_handler_sinks_to_owner_personal_kb(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    port = _FakePort()
    monkeypatch.setattr(personal_sink, "build_knowledge_index_port", lambda _s: port)
    owner, record_id = uuid.uuid4(), uuid.uuid4()
    event = SimpleNamespace(
        payload={
            "owner_user_id": str(owner),
            "title": "季度小结",
            "content": "结论……",
            "source_record_id": str(record_id),
        }
    )
    await personal_sink.handle_personal_knowledge_sink(db, event)

    assert port.captured is not None
    assert port.captured.uploader_id == owner
    assert port.captured.category == "ai_output"
    assert port.captured.document_id == record_id  # 复用产出记录 id → 重入幂等
    assert port.captured.title == "季度小结"
    # 个人库已按产出人建立，命令指向该库
    kb_id = (
        await db.execute(
            select(KnowledgeBase.id).where(KnowledgeBase.owner_user_id == owner)
        )
    ).scalar_one()
    assert port.captured.knowledge_base_id == kb_id


async def test_enqueue_is_idempotent_per_record(db: AsyncSession) -> None:
    owner, record_id = uuid.uuid4(), uuid.uuid4()
    for _ in range(2):
        await personal_sink.enqueue_personal_knowledge_sink(
            db, owner_user_id=owner, title="t", content="c", source_record_id=record_id
        )
    await db.commit()
    total = (
        await db.execute(
            select(func.count())
            .select_from(OutboxEvent)
            .where(OutboxEvent.event_type == personal_sink.PERSONAL_KNOWLEDGE_SINK_V1)
        )
    ).scalar_one()
    assert total == 1  # 同一产出记录只登记一次
