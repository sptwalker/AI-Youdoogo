"""Characterize Organization Structure transaction and roster semantics."""

import uuid
from collections.abc import AsyncGenerator

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.contexts.foundations.organization_structure.entrypoints import (
    operations as organization,
)
from app.contexts.shared_kernel import RuleViolation
from app.models import Base
from app.models.agent import AgentRole
from app.models.discussion import DiscussionChannel
from app.models.system import COMPANY, SysDepartment
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


async def _root(db: AsyncSession) -> SysDepartment:
    root = SysDepartment(
        name="公司",
        code="company",
        node_type=COMPANY,
        level=0,
        path="/",
    )
    db.add(root)
    await db.commit()
    return root


async def test_create_department_commits_channel_and_source_change_together(
    db: AsyncSession,
) -> None:
    root = await _root(db)

    department = await organization.create_department(
        db, name="研发部", parent_id=root.id, code=None
    )

    channel = (
        await db.execute(
            select(DiscussionChannel).where(
                DiscussionChannel.department_id == department.department_id
            )
        )
    ).scalar_one()
    event = (
        await db.execute(
            select(OutboxEvent).where(
                OutboxEvent.aggregate_id == department.department_id,
                OutboxEvent.event_type == "environment.source.changed.v1",
            )
        )
    ).scalar_one()
    assert channel.name == "研发部讨论区"
    assert event.payload["source_type"] == "organization"
    assert department.path == f"/{department.department_id}/"


async def test_company_name_cannot_change(db: AsyncSession) -> None:
    root = await _root(db)

    with pytest.raises(RuleViolation, match="公司根节点名称不可改"):
        await organization.update_department(
            db,
            department_id=root.id,
            name="新公司",
            sort_order=None,
        )


async def test_tree_count_includes_personal_assistants_but_roster_excludes_them(
    db: AsyncSession,
) -> None:
    root = await _root(db)
    department = await organization.create_department(
        db, name="产品部", parent_id=root.id, code=None
    )
    db.add_all(
        [
            AgentRole(
                name="产品专家",
                prompt_template="x",
                department_id=department.department_id,
                tier="member",
            ),
            AgentRole(
                name="个人助理",
                prompt_template="x",
                department_id=department.department_id,
                owner_user_id=uuid.uuid4(),
                tier="director",
            ),
        ]
    )
    await db.commit()

    tree = await organization.get_snapshot(db)
    employees = await organization.list_department_employees(
        db, department.department_id
    )

    assert tree.roots[0].children[0].employee_count == 2
    assert [employee.name for employee in employees] == ["产品专家"]


async def test_department_roster_orders_by_tier_then_creation(db: AsyncSession) -> None:
    root = await _root(db)
    department = await organization.create_department(
        db, name="运营部", parent_id=root.id, code=None
    )
    db.add_all(
        [
            AgentRole(
                name="普通员工",
                prompt_template="x",
                department_id=department.department_id,
                tier="member",
            ),
            AgentRole(
                name="部门总监",
                prompt_template="x",
                department_id=department.department_id,
                tier="director",
            ),
        ]
    )
    await db.commit()

    employees = await organization.list_department_employees(
        db, department.department_id
    )

    assert [employee.name for employee in employees] == ["部门总监", "普通员工"]
