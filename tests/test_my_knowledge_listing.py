"""B1.2 个人知识按库隔离列出 单测（docs/27 阶段 B）：list_documents 的 knowledge_base_id 过滤。

个人知识检索/问答的隔离靠 visible_kb_ids=(本人库,)（既有杠杆，别处已测）；
本测聚焦本阶段新增的「按库过滤列出」——本人库只列本人条目，且不传过滤不回归组织列出。
离线 sqlite，直接写 KnowledgeFile 行。
"""

import uuid
from collections.abc import AsyncGenerator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.contexts.foundations.knowledge.knowledge_indexing.public import list_documents
from app.models import Base
from app.models.knowledge import KnowledgeFile


@pytest.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


def _file(kb_id: uuid.UUID, name: str) -> KnowledgeFile:
    return KnowledgeFile(
        id=uuid.uuid4(),
        file_name=name,
        knowledge_base_id=kb_id,
        uploader_id=uuid.uuid4(),
        storage_path="inline",
        status="indexed",
    )


async def test_filter_lists_only_that_base(db: AsyncSession) -> None:
    mine, other = uuid.uuid4(), uuid.uuid4()
    db.add_all([_file(mine, "我的1"), _file(mine, "我的2"), _file(other, "他人1")])
    await db.commit()

    docs = await list_documents(db, knowledge_base_id=mine)
    assert {d.file_name for d in docs} == {"我的1", "我的2"}  # 仅本人库条目


async def test_no_filter_lists_all(db: AsyncSession) -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    db.add_all([_file(a, "甲"), _file(b, "乙")])
    await db.commit()

    docs = await list_documents(db)  # 组织级列出不回归
    assert {d.file_name for d in docs} == {"甲", "乙"}
