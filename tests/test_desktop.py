"""真人工作桌面 F5a 单测：按人隔离 + 四类待办合并 + 负向（内存 SQLite）。"""

import uuid
from collections.abc import AsyncGenerator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import Base
from app.models.meeting import MeetingResolution
from app.models.proposal import APPROVED, REVIEWED, ProposalCard
from app.models.system import SysDepartment, SysUser
from app.models.task import TaskCard
from app.services import collab_service, desktop_service
from app.services.task_flow import ACCEPTED, REPORTED


@pytest.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


def _user(role: str) -> SysUser:
    return SysUser(username=f"u{uuid.uuid4().hex[:6]}", password_hash="x", role_code=role)


def _kinds(desktop: dict) -> set[str]:
    return {p["kind"] for p in desktop["pending"]}


async def test_task_scoped_per_user(db: AsyncSession) -> None:
    """待验收任务按创建人隔离；admin 全见。"""
    a, b, admin = _user("member"), _user("member"), _user("admin")
    db.add_all([a, b, admin])
    await db.commit()
    db.add(TaskCard(title="A的任务", task_type="manual", status=REPORTED, creator_id=a.id))
    await db.commit()

    a_desk = await desktop_service.get_desktop(db, a)
    b_desk = await desktop_service.get_desktop(db, b)
    admin_desk = await desktop_service.get_desktop(db, admin)
    a_task_ids = [p["id"] for p in a_desk["pending"] if p["kind"] == "task"]
    assert len(a_task_ids) == 1  # A 见自己创建的
    assert not [p for p in b_desk["pending"] if p["kind"] == "task"]  # B 不见
    assert len([p for p in admin_desk["pending"] if p["kind"] == "task"]) == 1  # admin 全见


async def test_proposal_resolution_only_managers(db: AsyncSession) -> None:
    """待评审提案/待确认决议只进 admin/executive 的桌面。"""
    member, execu = _user("member"), _user("executive")
    db.add_all([member, execu])
    await db.commit()
    db.add(ProposalCard(code="P1", title="提案", background="b", plan="p",
                        status=REVIEWED, creator_id=member.id))
    db.add(MeetingResolution(meeting_id=uuid.uuid4(), content="决议", is_confirmed=False))
    await db.commit()

    assert _kinds(await desktop_service.get_desktop(db, execu)) >= {"proposal", "resolution"}
    assert not _kinds(await desktop_service.get_desktop(db, member)) & {"proposal", "resolution"}


async def test_collab_scoped_by_supervisor(db: AsyncSession) -> None:
    """待复核协作请求按目标部门主管隔离。"""
    boss, other = _user("member"), _user("member")
    db.add_all([boss, other])
    await db.commit()
    dept = SysDepartment(name="D", code="d", supervisor_user_id=boss.id)
    db.add(dept)
    await db.commit()
    await collab_service.create_request(db, target_department_id=dept.id, title="跨部门请求")

    assert "collab" in _kinds(await desktop_service.get_desktop(db, boss))
    assert "collab" not in _kinds(await desktop_service.get_desktop(db, other))


async def test_settled_not_pending_and_my_tasks(db: AsyncSession) -> None:
    """已验收任务不在待办、不在我的任务（非终态）；进行中的进我的任务。"""
    a = _user("member")
    db.add(a)
    await db.commit()
    db.add(TaskCard(title="已验收", task_type="manual", status=ACCEPTED, creator_id=a.id))
    db.add(TaskCard(title="进行中", task_type="manual", status=REPORTED, creator_id=a.id))
    await db.commit()

    desk = await desktop_service.get_desktop(db, a)
    assert [p["title"] for p in desk["pending"] if p["kind"] == "task"] == ["进行中"]
    assert [t["title"] for t in desk["my_tasks"]] == ["进行中"]  # 终态 accepted 被排除


async def test_approved_proposal_not_pending(db: AsyncSession) -> None:
    admin = _user("admin")
    db.add(admin)
    await db.commit()
    db.add(ProposalCard(code="P2", title="已通过", background="b", plan="p",
                        status=APPROVED, creator_id=admin.id))
    await db.commit()
    assert "proposal" not in _kinds(await desktop_service.get_desktop(db, admin))
