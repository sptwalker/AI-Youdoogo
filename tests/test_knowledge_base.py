"""知识集合化 F2 单测：KB CRUD 约束 + scope 可见范围隔离（内存 SQLite）。"""

import uuid
from collections.abc import AsyncGenerator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.exceptions import AppError
from app.knowledge.scope import resolve_visible_kb_ids
from app.models import Base
from app.models.knowledge import KnowledgeBase, KnowledgeFile
from app.models.system import SysDepartment
from app.services import knowledge_base_service as kb_svc


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        # 公司公共库种子（生产在迁移 012 里，SQLite 单测手工建）
        s.add(
            KnowledgeBase(
                name="公司公共知识库", code="kb_public", scope="company", is_default=True
            )
        )
        await s.commit()
        yield s
    await engine.dispose()


async def test_create_scopes(session: AsyncSession) -> None:
    """三档 scope 建库；department/personal 缺归属时拒绝。"""
    dept_id, agent_id = uuid.uuid4(), uuid.uuid4()
    assert (await kb_svc.create_kb(session, name="A", scope="company")).scope == "company"
    d = await kb_svc.create_kb(session, name="B", scope="department", department_id=dept_id)
    assert d.department_id == dept_id
    p = await kb_svc.create_kb(session, name="C", scope="personal", owner_agent_id=agent_id)
    assert p.owner_agent_id == agent_id
    with pytest.raises(AppError, match="部门"):
        await kb_svc.create_kb(session, name="D", scope="department")
    with pytest.raises(AppError, match="智能体"):
        await kb_svc.create_kb(session, name="E", scope="personal")


async def test_default_kb_not_deletable(session: AsyncSession) -> None:
    default = await kb_svc.get_default_kb(session)
    with pytest.raises(AppError, match="不可删除"):
        await kb_svc.delete_kb(session, default.id)


async def test_delete_blocked_by_files(session: AsyncSession) -> None:
    kb = await kb_svc.create_kb(session, name="有文件", scope="company")
    session.add(
        KnowledgeFile(
            file_name="f", knowledge_base_id=kb.id, uploader_id=uuid.uuid4(), storage_path="inline"
        )
    )
    await session.commit()
    with pytest.raises(AppError, match="文档"):
        await kb_svc.delete_kb(session, kb.id)


async def test_visible_scope_isolation(session: AsyncSession) -> None:
    """契约②减法隔离：admin 全见；本部门见本部门机密+自己私库；外人只见公司公共。"""
    dept_id = uuid.uuid4()
    session.add(SysDepartment(id=dept_id, name="财务", code="fin", path=f"/{dept_id}/"))
    conf = await kb_svc.create_kb(
        session, name="机密", scope="department", department_id=dept_id, is_confidential=True
    )
    agent_a, agent_b = uuid.uuid4(), uuid.uuid4()
    pa = await kb_svc.create_kb(session, name="A私库", scope="personal", owner_agent_id=agent_a)
    pb = await kb_svc.create_kb(session, name="B私库", scope="personal", owner_agent_id=agent_b)
    default = await kb_svc.get_default_kb(session)

    # admin 全库可见
    admin_ids = set(await resolve_visible_kb_ids(session, department_id=None, is_admin=True))
    assert {conf.id, pa.id, pb.id, default.id}.issubset(admin_ids)

    # 本部门 A 员工：公司公共 + 本部门机密 + 自己私库；不见 B 私库
    a_ids = await resolve_visible_kb_ids(
        session, department_id=dept_id, owner_agent_id=agent_a
    )
    assert default.id in a_ids and conf.id in a_ids and pa.id in a_ids
    assert pb.id not in a_ids

    # 无部门外人：只见公司公共，不见机密/他人私库
    out_ids = await resolve_visible_kb_ids(session, department_id=None, owner_agent_id=None)
    assert default.id in out_ids
    assert conf.id not in out_ids and pa.id not in out_ids
