"""任务卡状态机（纯）+ Task Management public API（内存 SQLite）单测。"""

import uuid
from collections.abc import AsyncGenerator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.contexts.business.task_management import public as task_management
from app.contexts.business.task_management.application.contracts import (
    CreateTaskRequest,
    DecomposeTaskRequest,
    EditTaskRequest,
    SubtaskRequest,
    TaskPrincipal,
    TransitionTaskRequest,
)
from app.contexts.business.task_management.domain import state_machine as task_flow
from app.contexts.shared_kernel import ApplicationError
from app.models import Base
from app.models.system import SysUser


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


def _admin_principal(user_id: uuid.UUID) -> TaskPrincipal:
    return TaskPrincipal(id=user_id, role_code="admin")


async def _create_task(
    session: AsyncSession,
    *,
    title: str,
    task_type: str,
    creator_id: uuid.UUID,
) -> uuid.UUID:
    created = await task_management.create_task(
        session,
        CreateTaskRequest(title=title, task_type=task_type, creator_id=creator_id),
    )
    return uuid.UUID(created["id"])


async def test_create_writes_initial_log(db: tuple[AsyncSession, uuid.UUID]) -> None:
    session, uid = db
    task_id = await _create_task(
        session,
        title="迭代复盘",
        task_type="analysis",
        creator_id=uid,
    )
    detail = await task_management.get_task(session, _admin_principal(uid), task_id)
    assert detail["task"]["status"] == task_flow.CREATED
    assert [log["to_status"] for log in detail["logs"]] == [task_flow.CREATED]


async def test_full_lifecycle(db: tuple[AsyncSession, uuid.UUID]) -> None:
    session, uid = db
    task_id = await _create_task(session, title="T", task_type="x", creator_id=uid)
    for to in (task_flow.DISPATCHED, task_flow.EXECUTING):
        await task_management.transition_task(
            session,
            TransitionTaskRequest(
                task_id=task_id,
                to_status=to,
                operator_id=uid,
                operator_role="admin",
            ),
        )
    reported = await task_management.transition_task(
        session,
        TransitionTaskRequest(
            task_id=task_id,
            to_status=task_flow.REPORTED,
            operator_id=uid,
            operator_role="admin",
            result_content="已完成",
        ),
    )
    assert reported["result_content"] == "已完成"
    accepted = await task_management.transition_task(
        session,
        TransitionTaskRequest(
            task_id=task_id,
            to_status=task_flow.ACCEPTED,
            operator_id=uid,
            operator_role="admin",
        ),
    )
    assert accepted["status"] == task_flow.ACCEPTED
    detail = await task_management.get_task(session, _admin_principal(uid), task_id)
    assert [log["to_status"] for log in detail["logs"]] == [
        task_flow.CREATED,
        task_flow.DISPATCHED,
        task_flow.EXECUTING,
        task_flow.REPORTED,
        task_flow.ACCEPTED,
    ]


async def test_illegal_transition_rejected(db: tuple[AsyncSession, uuid.UUID]) -> None:
    session, uid = db
    task_id = await _create_task(session, title="T", task_type="x", creator_id=uid)
    with pytest.raises(ApplicationError, match="非法状态流转"):
        await task_management.transition_task(
            session,
            TransitionTaskRequest(
                task_id=task_id,
                to_status=task_flow.ACCEPTED,
                operator_id=uid,
                operator_role="admin",
            ),
        )


async def test_decompose_creates_children(db: tuple[AsyncSession, uuid.UUID]) -> None:
    session, uid = db
    parent_id = await _create_task(session, title="大任务", task_type="x", creator_id=uid)
    children = await task_management.decompose_task(
        session,
        DecomposeTaskRequest(
            parent_id=parent_id,
            creator_id=uid,
            subtasks=(
                SubtaskRequest(title="子1"),
                SubtaskRequest(title="子2", task_type="y"),
            ),
        ),
    )
    assert len(children) == 2
    assert all(child["parent_id"] == str(parent_id) for child in children)


async def test_list_limit_caps_rows(db: tuple[AsyncSession, uuid.UUID]) -> None:
    """列表默认上限防全量返回（R2 防 OOM）。"""
    session, uid = db
    for i in range(5):
        await _create_task(session, title=f"T{i}", task_type="x", creator_id=uid)
    principal = _admin_principal(uid)
    assert len(await task_management.list_tasks(session, principal, status=None, limit=3)) == 3
    assert len(await task_management.list_tasks(session, principal, status=None, limit=100)) == 5


def test_assert_editable_guard() -> None:
    """P2-12：仅 created/rejected 未开跑可编辑，其余状态守卫报错。"""
    task_flow.assert_editable(task_flow.CREATED)
    task_flow.assert_editable(task_flow.REJECTED)
    with pytest.raises(ApplicationError, match="不可编辑"):
        task_flow.assert_editable(task_flow.EXECUTING)


async def test_edit_reassigns_pre_run_task(db: tuple[AsyncSession, uuid.UUID]) -> None:
    """P2-12：created 任务可改标题 + 补指派智能体。"""
    session, uid = db
    agent_id = uuid.uuid4()
    task_id = await _create_task(session, title="T", task_type="x", creator_id=uid)
    view = await task_management.edit_task(
        session,
        EditTaskRequest(task_id=task_id, title="改名", assignee_agent_id=agent_id),
    )
    assert view["title"] == "改名"
    assert view["assignee_agent_id"] == str(agent_id)


async def test_edit_rejected_after_dispatch(db: tuple[AsyncSession, uuid.UUID]) -> None:
    """P2-12：已分发（开跑）任务不可再编辑。"""
    session, uid = db
    task_id = await _create_task(session, title="T", task_type="x", creator_id=uid)
    await task_management.transition_task(
        session,
        TransitionTaskRequest(
            task_id=task_id,
            to_status=task_flow.DISPATCHED,
            operator_id=uid,
            operator_role="admin",
        ),
    )
    with pytest.raises(ApplicationError, match="不可编辑"):
        await task_management.edit_task(session, EditTaskRequest(task_id=task_id, title="x"))
