"""F4b 显式授权单测：check_role + granted_kb_ids(user/部门/过期) + visible_kb_ids(scope∪grant)。"""

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.exceptions import AppError
from app.models import Base
from app.models.knowledge import KnowledgeBase
from app.models.resource_grant import ResourceGrant
from app.models.system import SysDepartment, SysUser
from app.services import permission_service, resource_grant_service


@pytest.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


def _user(dept_id: uuid.UUID | None, role: str = "member") -> SysUser:
    return SysUser(username=f"u{uuid.uuid4().hex[:6]}", password_hash="x", role_code=role,
                   department_id=dept_id)


def test_check_role() -> None:
    admin = _user(None, "admin")
    permission_service.check_role(admin, "admin")  # 放行
    with pytest.raises(AppError, match="无权限"):
        permission_service.check_role(_user(None, "member"), "admin", "executive")


async def _grant(db: AsyncSession, *, kb_id: uuid.UUID, gtype: str, gid: uuid.UUID,
                 expires: datetime | None = None) -> None:
    db.add(ResourceGrant(resource_type="knowledge_base", resource_id=kb_id,
                         grantee_type=gtype, grantee_id=gid, expires_at=expires))
    await db.commit()


async def test_granted_kb_direct_user(db: AsyncSession) -> None:
    user = _user(None)
    db.add(user)
    kb = KnowledgeBase(name="X", code="x", scope="department")
    db.add(kb)
    await db.commit()
    await _grant(db, kb_id=kb.id, gtype="user", gid=user.id)
    assert await resource_grant_service.granted_kb_ids(db, user) == [kb.id]


async def test_granted_kb_department_subtree(db: AsyncSession) -> None:
    root, dept_a, dept_c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    db.add(SysDepartment(id=dept_a, name="A", code="a", path=f"/{root}/{dept_a}/"))
    kb = KnowledgeBase(name="X", code="x", scope="department")
    db.add(kb)
    await db.commit()
    # 授权给 dept_a → 该部门 user 命中
    await _grant(db, kb_id=kb.id, gtype="department", gid=dept_a)
    assert kb.id in await resource_grant_service.granted_kb_ids(db, _user(dept_a))
    # 授权给不相关 dept_c → 不命中
    assert kb.id not in await resource_grant_service.granted_kb_ids(db, _user(dept_c))


async def test_granted_kb_expired_excluded(db: AsyncSession) -> None:
    user = _user(None)
    db.add(user)
    kb = KnowledgeBase(name="X", code="x", scope="department")
    db.add(kb)
    await db.commit()
    past = datetime.now(UTC) - timedelta(days=1)
    await _grant(db, kb_id=kb.id, gtype="user", gid=user.id, expires=past)
    assert await resource_grant_service.granted_kb_ids(db, user) == []


async def test_visible_kb_merges_scope_and_grant(db: AsyncSession) -> None:
    """机密且不在 scope 的 KB，经 grant 后对目标 user 可见（scope ∪ grant）。"""
    other_dept = uuid.uuid4()
    db.add(SysDepartment(id=other_dept, name="B", code="b", path=f"/{other_dept}/"))
    user = _user(None)  # 无部门 → 默认只见公司公共库
    db.add(user)
    conf = KnowledgeBase(name="机密", code="c", scope="department",
                         department_id=other_dept, is_confidential=True)
    db.add(conf)
    await db.commit()
    # 未授权：不可见
    assert conf.id not in await permission_service.visible_kb_ids(db, user)
    # 授权后：可见
    await _grant(db, kb_id=conf.id, gtype="user", gid=user.id)
    assert conf.id in await permission_service.visible_kb_ids(db, user)
