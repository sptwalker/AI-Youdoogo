"""组织架构 F1 单测：幂等种子 / 树 / 层级校验 / 主管 / 员工（内存 SQLite）。"""

import uuid
from collections.abc import AsyncGenerator

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.contexts.foundations.organization_structure.entrypoints import (
    operations as organization,
)
from app.contexts.foundations.workforce.expert_management import public as experts
from app.contexts.shared_kernel import ApplicationError
from app.models import Base
from app.models.agent import AgentRole
from app.models.system import SysDepartment, SysUser


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
    r1 = await organization.seed_org_template(session, ceo_user_id=ceo)
    assert r1 == {"root": "创想悦动", "departments": 10, "execs": 8, "directors": 10}
    depts1, agents1 = await _count(session, SysDepartment), await _count(session, AgentRole)
    assert depts1 == 11 and agents1 == 18  # 根+10部门；8顾问+10总监助理
    root = await _dept(session, "company")
    first = await _dept(session, "dept_product_base")
    assert isinstance(root.id, uuid.UUID) and root.path == f"/{root.id}/"
    assert isinstance(first.id, uuid.UUID) and first.path == f"/{root.id}/{first.id}/"

    # 重跑不造重复（按 code upsert）
    await organization.seed_org_template(session, ceo_user_id=ceo)
    assert await _count(session, SysDepartment) == 11
    assert await _count(session, AgentRole) == 18


async def test_seed_accepts_default_ceo_and_leaves_supervisor_unset(
    ctx: tuple[AsyncSession, uuid.UUID],
) -> None:
    session, _ = ctx

    result = await organization.seed_org_template(session)

    assert result["root"] == "创想悦动"
    assert (await _dept(session, "company")).supervisor_user_id is None


async def test_seed_wires_root_supervisor_and_report_lines(
    ctx: tuple[AsyncSession, uuid.UUID],
) -> None:
    session, ceo = ctx
    await organization.seed_org_template(session, ceo_user_id=ceo)
    root = await _dept(session, "company")
    assert root.supervisor_user_id == ceo and root.level == 0  # CEO=真人主管
    # 财务部总监 report_to CFO
    dir_fin = await _agent(session, "dir_finance")
    cfo = await _agent(session, "exec_cfo")
    assert dir_fin.report_to_id == cfo.id and dir_fin.tier == "director" and cfo.tier == "exec"
    assert dir_fin.model_role == "daily" and dir_fin.duty == "财务部总监助理"
    assert cfo.model_role == "reasoning" and cfo.duty == "CFO"
    assert dir_fin.is_seed is True and cfo.is_seed is True


async def test_tree_shape(ctx: tuple[AsyncSession, uuid.UUID]) -> None:
    session, ceo = ctx
    await organization.seed_org_template(session, ceo_user_id=ceo)
    tree = await organization.get_snapshot(session)
    assert len(tree.roots) == 1 and tree.roots[0].department.node_type == "company"
    assert len(tree.roots[0].children) == 10  # 10 个一级部门
    assert tree.roots[0].department.department_id == (await _dept(session, "company")).id
    assert [child.department.name for child in tree.roots[0].children] == [
        "基础产品部",
        "游戏研发部",
        "平台运营部",
        "商务合作部",
        "营销销售部",
        "品牌宣传部",
        "人资行政部",
        "财务部",
        "公共设计组",
        "法务部",
    ]
    assert all(
        isinstance(child.department.department_id, uuid.UUID)
        for child in tree.roots[0].children
    )


async def test_depth_limited_to_two(ctx: tuple[AsyncSession, uuid.UUID]) -> None:
    session, ceo = ctx
    await organization.seed_org_template(session, ceo_user_id=ceo)
    l1 = await _dept(session, "dept_hr")
    l2 = await organization.create_department(
        session, name="招聘组", parent_id=l1.id, code=None
    )
    assert l2.level == 2 and l2.node_type == "dept_l2"
    with pytest.raises(ApplicationError, match="最多两级"):
        await organization.create_department(
            session, name="太深了", parent_id=l2.department_id, code=None
        )


async def test_delete_blocked_by_children_and_employees(
    ctx: tuple[AsyncSession, uuid.UUID],
) -> None:
    session, ceo = ctx
    await organization.seed_org_template(session, ceo_user_id=ceo)
    hr = await _dept(session, "dept_hr")
    with pytest.raises(ApplicationError, match="智能体员工"):  # 有总监员工
        await organization.delete_department(session, hr.id)


async def test_set_supervisor(ctx: tuple[AsyncSession, uuid.UUID]) -> None:
    session, ceo = ctx
    await organization.seed_org_template(session, ceo_user_id=ceo)
    hr = await _dept(session, "dept_hr")
    updated = await organization.set_supervisor(
        session, department_id=hr.id, supervisor_user_id=ceo
    )
    assert updated.supervisor_user_id == ceo


async def test_seed_agent_deletable_and_renamable(ctx: tuple[AsyncSession, uuid.UUID]) -> None:
    """骨架也可改名与删除（is_seed 仅作模板位标记，不再拦截）。"""
    session, ceo = ctx
    await organization.seed_org_template(session, ceo_user_id=ceo)
    cfo = await _agent(session, "exec_cfo")
    renamed = await experts.update_expert(
        session,
        expert_id=cfo.id,
        name="财务大脑",
        prompt_template=None,
        duty=None,
        model_role=None,
        is_active=None,
        permission_scope=None,
        tools=None,
        title=None,
        tier=None,
        report_to_id=None,
        department_id=None,
    )
    assert renamed.name == "财务大脑"
    await experts.delete_expert(session, cfo.id)
    assert (await session.get(AgentRole, cfo.id)).is_delete is True
