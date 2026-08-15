"""A4：收件箱读态持久化 + 批量处理 + 红线隔离（内存 SQLite）。"""

from collections.abc import AsyncGenerator

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.contexts.business.task_management.domain.state_machine import REPORTED
from app.contexts.business.work_desktop import public as work_desktop
from app.contexts.shared_kernel import RuleViolation
from app.models import Base
from app.models.inbox_state import InboxItemState
from app.models.system import SysUser
from app.models.task import TaskCard


@pytest.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


def _principal(user: SysUser) -> work_desktop.DesktopPrincipal:
    return work_desktop.DesktopPrincipal(
        id=user.id,
        display_name=user.username,
        role_code=user.role_code,
        department_id=None,
    )


async def _seed_reported_task(db: AsyncSession, owner: SysUser, title: str) -> TaskCard:
    task = TaskCard(title=title, task_type="manual", status=REPORTED, creator_id=owner.id)
    db.add(task)
    await db.commit()
    return task


async def test_pending_carries_score_and_sorted_desc(db: AsyncSession) -> None:
    """收件箱每项带 score，且按分数降序。"""
    u = SysUser(username="u1", password_hash="x", role_code="member")
    db.add(u)
    await db.commit()
    await _seed_reported_task(db, u, "任务一")
    await _seed_reported_task(db, u, "任务二")

    desk = await work_desktop.get_desktop(db, _principal(u))
    pending = desk["pending"]
    assert all("score" in p for p in pending)
    scores = [p["score"] for p in pending]
    assert scores == sorted(scores, reverse=True)


async def test_mark_persists_read_state_and_desktop_reflects_it(db: AsyncSession) -> None:
    """批量置读/处理态落库，重取桌面回显。"""
    u = SysUser(username="u2", password_hash="x", role_code="member")
    db.add(u)
    await db.commit()
    task = await _seed_reported_task(db, u, "待读任务")

    ref = (work_desktop.InboxItemRef(kind="task", id=task.id),)
    result = await work_desktop.mark_inbox(db, _principal(u), ref, is_read=True, is_processed=True)
    assert result == {"marked": 1}

    desk = await work_desktop.get_desktop(db, _principal(u))
    item = next(p for p in desk["pending"] if p["id"] == str(task.id))
    assert item["is_read"] is True
    assert item["is_processed"] is True


async def test_mark_without_action_rejected(db: AsyncSession) -> None:
    """既不置读也不置处理 → 拒绝（红线：批量处理需真人明确动作）。"""
    u = SysUser(username="u3", password_hash="x", role_code="member")
    db.add(u)
    await db.commit()
    task = await _seed_reported_task(db, u, "任务")
    ref = (work_desktop.InboxItemRef(kind="task", id=task.id),)
    with pytest.raises(RuleViolation):
        await work_desktop.mark_inbox(db, _principal(u), ref)


async def test_mark_touches_only_inbox_state_not_source(db: AsyncSession) -> None:
    """红线：批量处理只写 inbox_item_state，不触碰来源聚合、不外发。"""
    u = SysUser(username="u4", password_hash="x", role_code="member")
    db.add(u)
    await db.commit()
    task = await _seed_reported_task(db, u, "来源不动")

    ref = (work_desktop.InboxItemRef(kind="task", id=task.id),)
    await work_desktop.mark_inbox(db, _principal(u), ref, is_read=True)

    # 来源任务状态原样（未被推进/未外发）
    refreshed = await db.get(TaskCard, task.id)
    assert refreshed is not None
    assert refreshed.status == REPORTED
    # 读态只落在本人的 inbox_item_state
    states = (await db.execute(select(InboxItemState))).scalars().all()
    assert len(states) == 1
    assert states[0].owner_user_id == u.id
    assert states[0].kind == "task"
    assert states[0].source_id == task.id
    assert states[0].is_read is True


async def test_read_state_isolated_per_owner(db: AsyncSession) -> None:
    """读态按 owner 行级隔离：他人置读不影响本人。"""
    a = SysUser(username="ua", password_hash="x", role_code="admin")
    b = SysUser(username="ub", password_hash="x", role_code="member")
    db.add_all([a, b])
    await db.commit()
    task = await _seed_reported_task(db, b, "B的任务")

    # admin a 把该项在自己收件箱标已读
    ref = (work_desktop.InboxItemRef(kind="task", id=task.id),)
    await work_desktop.mark_inbox(db, _principal(a), ref, is_read=True)

    b_desk = await work_desktop.get_desktop(db, _principal(b))
    b_item = next(p for p in b_desk["pending"] if p["id"] == str(task.id))
    assert b_item["is_read"] is False  # 本人未读，不受 admin 影响
