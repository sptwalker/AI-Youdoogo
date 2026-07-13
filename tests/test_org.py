"""组织架构 F1 单测：幂等种子 / 树 / 层级校验 / 主管 / 员工（内存 SQLite）。"""

import uuid
from collections.abc import AsyncGenerator

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.exceptions import AppError
from app.models import Base
from app.models.agent import AgentRole
from app.models.system import SysDepartment, SysUser
from app.services import agent_role_service, org_service, org_template


@pytest.fixture
async def ctx() -> AsyncGenerator[tuple[AsyncSession, uuid.UUID], None]:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        ceo = SysUser(username="ceo", password_hash="x", real_name="老板", role_code="admin")
        session.add(ceo)
        await session.commit()
        yield session, ceo.id
    await engine.dispose()


async def _count(session: AsyncSession, model) -> int:
    return (await session.execute(select(func.count()).select_from(model))).scalar_one()


async def _dept(session: AsyncSession, code: str) -> SysDepartment:
    return (
        await session.execute(select(SysDepartment).where(SysDepartment.code == code))
    ).scalar_one()


async def _agent(session: AsyncSession, code: str) -> AgentRole:
    return (await session.execute(select(AgentRole).where(AgentRole.code == code))).scalar_one()


async def test_seed_idempotent(ctx: tuple[AsyncSession, uuid.UUID]) -> None:
    session, ceo = ctx
    r1 = await org_template.seed_org_template(session, ceo_user_id=ceo)
    assert r1 == {"root": "创想悦动", "departments": 8, "execs": 7, "directors": 8}
    depts1, agents1 = await _count(session, SysDepartment), await _count(session, AgentRole)
    assert depts1 == 9 and agents1 == 15  # 根+8部门；7高管+8总监

    # 重跑不造重复（按 code upsert）
    await org_template.seed_org_template(session, ceo_user_id=ceo)
    assert await _count(session, SysDepartment) == 9
    assert await _count(session, AgentRole) == 15


async def test_seed_wires_root_supervisor_and_report_lines(
    ctx: tuple[AsyncSession, uuid.UUID],
) -> None:
    session, ceo = ctx
    await org_template.seed_org_template(session, ceo_user_id=ceo)
    root = await _dept(session, "company")
    assert root.supervisor_user_id == ceo and root.level == 0  # CEO=真人主管
    # 财务部总监 report_to CFO
    dir_fin = await _agent(session, "dir_finance")
    cfo = await _agent(session, "exec_cfo")
    assert dir_fin.report_to_id == cfo.id and dir_fin.tier == "director" and cfo.tier == "exec"


async def test_tree_shape(ctx: tuple[AsyncSession, uuid.UUID]) -> None:
    session, ceo = ctx
    await org_template.seed_org_template(session, ceo_user_id=ceo)
    tree = await org_service.get_tree(session)
    assert len(tree) == 1 and tree[0]["node_type"] == "company"
    assert len(tree[0]["children"]) == 8  # 8 个一级部门


async def test_depth_limited_to_two(ctx: tuple[AsyncSession, uuid.UUID]) -> None:
    session, ceo = ctx
    await org_template.seed_org_template(session, ceo_user_id=ceo)
    l1 = await _dept(session, "dept_hr")
    l2 = await org_service.create_node(session, name="招聘组", parent_id=l1.id)
    assert l2.level == 2 and l2.node_type == "dept_l2"
    with pytest.raises(AppError, match="最多两级"):
        await org_service.create_node(session, name="太深了", parent_id=l2.id)


async def test_delete_blocked_by_children_and_employees(
    ctx: tuple[AsyncSession, uuid.UUID],
) -> None:
    session, ceo = ctx
    await org_template.seed_org_template(session, ceo_user_id=ceo)
    hr = await _dept(session, "dept_hr")
    with pytest.raises(AppError, match="智能体员工"):  # 有总监员工
        await org_service.delete_node(session, hr.id)


async def test_set_supervisor(ctx: tuple[AsyncSession, uuid.UUID]) -> None:
    session, ceo = ctx
    await org_template.seed_org_template(session, ceo_user_id=ceo)
    hr = await _dept(session, "dept_hr")
    updated = await org_service.set_supervisor(session, hr.id, ceo)
    assert updated.supervisor_user_id == ceo


async def test_seed_agent_protected_from_delete(ctx: tuple[AsyncSession, uuid.UUID]) -> None:
    session, ceo = ctx
    await org_template.seed_org_template(session, ceo_user_id=ceo)
    cfo = await _agent(session, "exec_cfo")
    with pytest.raises(AppError, match="不可删除"):
        await agent_role_service.delete_agent_role(session, cfo.id)
