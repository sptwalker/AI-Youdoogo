"""任务卡状态机（纯）+ 任务服务（内存 SQLite）单测。"""

import uuid
from collections.abc import AsyncGenerator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.contexts.shared_kernel import ApplicationError
from app.models import Base
from app.models.system import SysUser
from app.services import task_flow, task_service


def test_valid_transitions() -> None:
    assert task_flow.can_transition(task_flow.CREATED, task_flow.DISPATCHED)
    assert task_flow.can_transition(task_flow.REPORTED, task_flow.ACCEPTED)
    assert task_flow.can_transition(task_flow.REJECTED, task_flow.DISPATCHED)


def test_invalid_transitions() -> None:
    assert not task_flow.can_transition(task_flow.CREATED, task_flow.ACCEPTED)
    assert not task_flow.can_transition(task_flow.ACCEPTED, task_flow.EXECUTING)  # 终态
    assert not task_flow.can_transition(task_flow.CANCELLED, task_flow.DISPATCHED)


def test_assert_transition_raises() -> None:
    with pytest.raises(ApplicationError, match="非法状态流转"):
        task_flow.assert_transition(task_flow.CREATED, task_flow.ACCEPTED)
    with pytest.raises(ApplicationError, match="未知任务状态"):
        task_flow.assert_transition(task_flow.CREATED, "bogus")


@pytest.fixture
async def db() -> AsyncGenerator[tuple[AsyncSession, uuid.UUID], None]:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        user = SysUser(username="boss", password_hash="x", role_code="admin")
        session.add(user)
        await session.commit()
        yield session, user.id
    await engine.dispose()


async def test_create_writes_initial_log(db: tuple[AsyncSession, uuid.UUID]) -> None:
    session, uid = db
    task = await task_service.create_task(
        session, title="迭代复盘", task_type="analysis", creator_id=uid
    )
    assert task.status == task_flow.CREATED
    logs = await task_service.list_logs(session, task.id)
    assert len(logs) == 1 and logs[0].to_status == task_flow.CREATED


async def test_full_lifecycle(db: tuple[AsyncSession, uuid.UUID]) -> None:
    session, uid = db
    task = await task_service.create_task(session, title="T", task_type="x", creator_id=uid)
    for to in (task_flow.DISPATCHED, task_flow.EXECUTING):
        await task_service.transition(session, task.id, to, operator_id=uid)
    reported = await task_service.transition(
        session, task.id, task_flow.REPORTED, operator_id=uid, result_content="已完成"
    )
    assert reported.result_content == "已完成"
    accepted = await task_service.transition(session, task.id, task_flow.ACCEPTED, operator_id=uid)
    assert accepted.status == task_flow.ACCEPTED
    logs = await task_service.list_logs(session, task.id)
    assert [x.to_status for x in logs] == [
        task_flow.CREATED, task_flow.DISPATCHED, task_flow.EXECUTING,
        task_flow.REPORTED, task_flow.ACCEPTED,
    ]


async def test_illegal_transition_rejected(db: tuple[AsyncSession, uuid.UUID]) -> None:
    session, uid = db
    task = await task_service.create_task(session, title="T", task_type="x", creator_id=uid)
    with pytest.raises(ApplicationError, match="非法状态流转"):
        await task_service.transition(session, task.id, task_flow.ACCEPTED, operator_id=uid)


async def test_decompose_creates_children(db: tuple[AsyncSession, uuid.UUID]) -> None:
    session, uid = db
    parent = await task_service.create_task(session, title="大任务", task_type="x", creator_id=uid)
    children = await task_service.decompose(
        session, parent.id,
        [{"title": "子1"}, {"title": "子2", "task_type": "y"}],
        creator_id=uid,
    )
    assert len(children) == 2
    assert all(c.parent_id == parent.id for c in children)
    subtasks = await task_service.list_tasks(session, parent_id=parent.id)
    assert len(subtasks) == 2


async def test_list_limit_caps_rows(db: tuple[AsyncSession, uuid.UUID]) -> None:
    """列表默认上限防全量返回（R2 防 OOM）。"""
    session, uid = db
    for i in range(5):
        await task_service.create_task(session, title=f"T{i}", task_type="x", creator_id=uid)
    assert len(await task_service.list_tasks(session, limit=3)) == 3
    assert len(await task_service.list_tasks(session)) == 5  # 默认 100 ≥ 全部
