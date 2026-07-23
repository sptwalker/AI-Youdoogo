"""Expert ORM rows are translated before crossing the execution boundary."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.contexts.foundations.workforce.expert_management.infrastructure.sqlalchemy_query import (
    SQLAlchemyExpertSnapshotQuery,
)
from app.models import Base
from app.models.agent import AgentRole


@pytest.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


async def test_expert_query_returns_versioned_immutable_snapshot(db: AsyncSession) -> None:
    role = AgentRole(
        name="数据专家",
        code="data_expert",
        title="分析师",
        prompt_template="仅依据授权数据分析。",
        model_role="reasoning",
        tools=["data_query", 123],
        permission_scope={"scope": "department", "level": 2},
    )
    db.add(role)
    await db.commit()
    await db.refresh(role)

    query = SQLAlchemyExpertSnapshotQuery(db)
    snapshot = await query.get_by_code("data_expert")

    assert snapshot is not None
    assert snapshot.expert_id == role.id
    assert snapshot.version == role.update_time.isoformat()
    assert snapshot.capability_keys == ("data_query",)
    assert dict(snapshot.permission_entries) == {"level": "2", "scope": "department"}
    assert await query.get_by_id(role.id) == snapshot
    assert await query.get_by_name("数据专家") == snapshot


async def test_expert_query_filters_inactive_and_deleted_rows(db: AsyncSession) -> None:
    inactive = AgentRole(
        id=uuid.uuid4(),
        name="停用专家",
        code="inactive",
        prompt_template="x",
        is_active=False,
    )
    deleted = AgentRole(
        id=uuid.uuid4(),
        name="已删除专家",
        code="deleted",
        prompt_template="x",
        is_delete=True,
    )
    db.add_all([inactive, deleted])
    await db.commit()

    query = SQLAlchemyExpertSnapshotQuery(db)
    assert await query.get_by_id(inactive.id) is None
    assert await query.get_by_id(deleted.id) is None
