"""已发布快照驱动执行（Module 4 / docs/23 §4.4）——内存 SQLite，验证 get_by_id 读哪份配置。

覆盖：有 current_release_id → 执行字段取冻结 release、组织字段仍取活行；
无指针 → 回落活行（零变更）；指针悬空（release 行缺失）→ 安全回落活行。
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.contexts.foundations.workforce.expert_management.infrastructure.sqlalchemy_query import (
    SQLAlchemyExpertSnapshotQuery,
)
from app.models import Base
from app.models.agent import AgentRole, ExpertRelease


@pytest.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _seed_role(session: AsyncSession, **overrides: object) -> AgentRole:
    role = AgentRole(
        name="运营总监助理",
        title="总监助理",
        prompt_template="活行草稿提示词",
        model_role="daily",
        tools=["deliver"],
        permission_scope={"deliver": "on"},
        **overrides,
    )
    session.add(role)
    await session.commit()
    return role


async def test_release_drives_execution_while_org_fields_stay_live(db: AsyncSession) -> None:
    role = await _seed_role(db)
    release = ExpertRelease(
        expert_id=role.id,
        version_no=3,
        prompt_template="v3 已发布提示词",
        model_role="reasoning",
        tools=["data_query"],
        permission_scope={"data_query": "ro"},
        duty=None,
    )
    db.add(release)
    await db.flush()
    # 发布后又编辑草稿（活行）——执行不应看到草稿；组织归属字段仍读活行
    role.prompt_template = "发布后又改的草稿"
    role.model_role = "daily"
    role.current_release_id = release.id
    role.title = "改名后的职位"
    await db.commit()

    snap = await SQLAlchemyExpertSnapshotQuery(db).get_by_id(role.id)

    assert snap is not None
    assert snap.version == "v3"
    assert snap.prompt_template == "v3 已发布提示词"  # 冻结 release，非草稿
    assert snap.model_role == "reasoning"
    assert snap.capability_keys == ("data_query",)
    assert snap.permission_entries == (("data_query", "ro"),)
    assert snap.title == "改名后的职位"  # 组织字段取活行


async def test_no_release_pointer_falls_back_to_live_row(db: AsyncSession) -> None:
    role = await _seed_role(db)

    snap = await SQLAlchemyExpertSnapshotQuery(db).get_by_id(role.id)

    assert snap is not None
    assert snap.prompt_template == "活行草稿提示词"
    assert snap.model_role == "daily"


async def test_dangling_release_pointer_falls_back_to_live_row(db: AsyncSession) -> None:
    role = await _seed_role(db, current_release_id=uuid.uuid4())

    snap = await SQLAlchemyExpertSnapshotQuery(db).get_by_id(role.id)

    assert snap is not None
    assert snap.prompt_template == "活行草稿提示词"
