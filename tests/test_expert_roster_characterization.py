"""Characterize Expert roster, partial update, and source-change behavior."""

import json
import uuid
from collections.abc import AsyncGenerator

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.contexts.foundations.workforce.expert_management import public as experts
from app.models import Base
from app.models.agent import AgentRole
from app.platform.outbox.model import OutboxEvent


@pytest.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def test_create_expert_commits_source_change_with_profile(db: AsyncSession) -> None:
    expert = await experts.create_expert(
        db,
        name="战略专家",
        prompt_template="分析战略",
        duty=None,
        model_role="daily",
        department_id=None,
        tools=["knowledge_search", {"key": "data_query", "enabled": True}],
        permission_scope={"scope": "department", "depth": 2},
        tier="member",
        title="",
        report_to_id=None,
    )

    event = (
        await db.execute(
            select(OutboxEvent).where(
                OutboxEvent.aggregate_id == expert.expert_id,
                OutboxEvent.event_type == "environment.source.changed.v1",
            )
        )
    ).scalar_one()
    assert event.payload["source_type"] == "expert"
    assert json.loads(expert.permission_scope_json) == {
        "scope": "department",
        "depth": 2,
    }
    assert json.loads(expert.tools_json)[1]["key"] == "data_query"


async def test_roster_includes_inactive_but_excludes_deleted_and_personal(
    db: AsyncSession,
) -> None:
    inactive = AgentRole(
        name="停用专家",
        prompt_template="x",
        is_active=False,
    )
    deleted = AgentRole(
        name="删除专家",
        prompt_template="x",
        is_delete=True,
    )
    personal = AgentRole(
        name="个人助理",
        prompt_template="x",
        owner_user_id=uuid.uuid4(),
    )
    db.add_all([inactive, deleted, personal])
    await db.commit()

    roster = await experts.list_expert_roster(db, include_personal=False)

    assert [expert.name for expert in roster] == ["停用专家"]


async def test_partial_update_ignores_empty_prompt_and_null_assignments(
    db: AsyncSession,
) -> None:
    department_id = uuid.uuid4()
    report_to_id = uuid.uuid4()
    expert = AgentRole(
        name="经营专家",
        prompt_template="保留提示词",
        department_id=department_id,
        report_to_id=report_to_id,
    )
    db.add(expert)
    await db.commit()

    updated = await experts.update_expert(
        db,
        expert_id=expert.id,
        name=None,
        prompt_template="",
        duty=None,
        model_role=None,
        is_active=None,
        permission_scope=None,
        tools=None,
        title=None,
        tier=None,
        department_id=None,
        report_to_id=None,
    )

    assert updated.prompt_template == "保留提示词"
    assert updated.department_id == department_id
    assert updated.report_to_id == report_to_id
