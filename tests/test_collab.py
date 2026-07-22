"""跨部门协作治理 F4c 单测：风险分级 + 既定授权 + 复核队列 + 复核（内存 SQLite）。"""

import uuid
from collections.abc import AsyncGenerator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.contexts.shared_kernel import ApplicationError
from app.models import Base
from app.models.system import SysDepartment
from app.services import collab_service


@pytest.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


def test_classify_risk() -> None:
    assert collab_service.classify_risk("finance") == "high"
    assert collab_service.classify_risk("hr") == "high"
    assert collab_service.classify_risk("analysis") == "low"
    assert collab_service.classify_risk(None) == "low"


async def test_authorize_and_has_authorization(db: AsyncSession) -> None:
    src, tgt = uuid.uuid4(), uuid.uuid4()
    await collab_service.authorize(
        db, source_department_id=src, target_department_id=tgt,
        collab_type="取数", authorized_by=uuid.uuid4(),
    )
    assert await collab_service.has_authorization(
        db, source_department_id=src, target_department_id=tgt, collab_type="取数"
    )
    # 类别不同 → 无授权
    assert not await collab_service.has_authorization(
        db, source_department_id=src, target_department_id=tgt, collab_type="立项"
    )


async def test_create_request_risk_auto_and_override(db: AsyncSession) -> None:
    tgt = uuid.uuid4()
    r1 = await collab_service.create_request(
        db, target_department_id=tgt, title="调预算", category="budget"
    )
    assert r1.risk_level == "high"  # 红线类别恒高
    r2 = await collab_service.create_request(
        db, target_department_id=tgt, title="取个数", category="analysis"
    )
    assert r2.risk_level == "low"
    r3 = await collab_service.create_request(
        db, target_department_id=tgt, title="手动升级", category="analysis", risk_level="high"
    )
    assert r3.risk_level == "high"  # 显式覆盖


async def test_review_queue_filters_by_supervisor(db: AsyncSession) -> None:
    boss, other = uuid.uuid4(), uuid.uuid4()
    dept_a = SysDepartment(name="A", code="a", supervisor_user_id=boss)
    dept_b = SysDepartment(name="B", code="b", supervisor_user_id=other)
    db.add_all([dept_a, dept_b])
    await db.commit()
    await collab_service.create_request(db, target_department_id=dept_a.id, title="给A")
    await collab_service.create_request(db, target_department_id=dept_b.id, title="给B")

    q = await collab_service.review_queue(db, supervisor_user_id=boss)
    assert len(q) == 1 and q[0]["title"] == "给A"
    # admin 见全部 pending
    q_admin = await collab_service.review_queue(db, supervisor_user_id=uuid.uuid4(), is_admin=True)
    assert len(q_admin) == 2


async def test_review_request(db: AsyncSession) -> None:
    tgt = uuid.uuid4()
    r = await collab_service.create_request(db, target_department_id=tgt, title="请求")
    reviewer = uuid.uuid4()
    approved = await collab_service.review_request(
        db, r.id, decision="approve", reviewer_id=reviewer, note="ok"
    )
    assert approved.status == "approved" and approved.reviewed_by == reviewer
    # 已复核不可再复核
    with pytest.raises(ApplicationError, match="不可复核"):
        await collab_service.review_request(db, r.id, decision="reject", reviewer_id=reviewer)
