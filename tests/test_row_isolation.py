"""行级可见性单测（H1.2，docs/16 P0-2）:普通员工只见本人/本部门；管理层全见。

测 permission_service 的判定/过滤纯逻辑 + 三域 list 的实际过滤（内存 SQLite）。
"""

import uuid
from collections.abc import AsyncGenerator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import Base
from app.models.meeting import MeetingInfo
from app.models.proposal import ProposalCard
from app.models.system import SysUser
from app.models.task import TaskCard
from app.services import meeting_service, permission_service, proposal_service, task_service


@pytest.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


def _user(role: str, dept: uuid.UUID | None = None) -> SysUser:
    return SysUser(
        id=uuid.uuid4(), username=f"u{uuid.uuid4().hex[:6]}", password_hash="x",
        role_code=role, department_id=dept,
    )


# ── 判定纯逻辑 ──────────────────────────────────────────
def test_can_see_privileged_sees_all() -> None:
    admin = _user("admin")
    other = uuid.uuid4()
    assert permission_service.can_see_row(admin, creator_id=other, department_id=uuid.uuid4())


def test_can_see_own_creation() -> None:
    m = _user("member")
    assert permission_service.can_see_row(m, creator_id=m.id)


def test_can_see_same_department() -> None:
    dept = uuid.uuid4()
    m = _user("member", dept)
    assert permission_service.can_see_row(m, creator_id=uuid.uuid4(), department_id=dept)


def test_can_see_assigned_to_self() -> None:
    m = _user("member")
    assert permission_service.can_see_row(
        m, creator_id=uuid.uuid4(), assignee_user_id=m.id
    )


def test_cannot_see_others() -> None:
    m = _user("member", uuid.uuid4())
    assert not permission_service.can_see_row(
        m, creator_id=uuid.uuid4(), department_id=uuid.uuid4()
    )


def test_assert_can_see_raises_404() -> None:
    from app.core.exceptions import AppError

    m = _user("member")
    with pytest.raises(AppError) as ei:
        permission_service.assert_can_see(m, creator_id=uuid.uuid4())
    assert ei.value.status_code == 404


# ── 三域 list 实际过滤 ──────────────────────────────────
async def test_proposal_list_row_filtered(db: AsyncSession) -> None:
    dept_a = uuid.uuid4()
    mine = _user("member", dept_a)
    other = _user("member", uuid.uuid4())
    db.add_all([
        ProposalCard(code="P1", title="我的", background="b", plan="p",
                     creator_id=mine.id, department_id=dept_a),
        ProposalCard(code="P2", title="同部门", background="b", plan="p",
                     creator_id=other.id, department_id=dept_a),
        ProposalCard(code="P3", title="他部门", background="b", plan="p",
                     creator_id=other.id, department_id=uuid.uuid4()),
    ])
    await db.commit()
    # 普通员工只见本人 + 本部门（P1+P2），不见他部门（P3）
    seen = await proposal_service.list_proposals(db, viewer=mine)
    codes = {p.code for p in seen}
    assert codes == {"P1", "P2"}
    # 管理层全见
    admin = _user("admin")
    assert len(await proposal_service.list_proposals(db, viewer=admin)) == 3
    # 无 viewer（内部调用）不过滤
    assert len(await proposal_service.list_proposals(db)) == 3


async def test_task_list_includes_assigned(db: AsyncSession) -> None:
    mine = _user("member", uuid.uuid4())
    boss = _user("member", uuid.uuid4())
    db.add_all([
        TaskCard(title="派给我", task_type="t", creator_id=boss.id,
                 assignee_user_id=mine.id, assignee_type="user"),
        TaskCard(title="别人的", task_type="t", creator_id=boss.id,
                 department_id=uuid.uuid4()),
    ])
    await db.commit()
    seen = await task_service.list_tasks(db, viewer=mine)
    titles = {t.title for t in seen}
    assert titles == {"派给我"}  # 派给自己的可见，别人的不可见


async def test_meeting_list_row_filtered(db: AsyncSession) -> None:
    dept = uuid.uuid4()
    mine = _user("member", dept)
    db.add_all([
        MeetingInfo(title="本部门会", creator_id=uuid.uuid4(), department_id=dept),
        MeetingInfo(title="他部门会", creator_id=uuid.uuid4(), department_id=uuid.uuid4()),
    ])
    await db.commit()
    seen = await meeting_service.list_meetings(db, viewer=mine)
    assert {m.title for m in seen} == {"本部门会"}
