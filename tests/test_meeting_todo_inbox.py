"""B3.1 会后纪要待办自动进收件箱（复用「决议→任务」链路，零新增后端代码）。

链路：闭会（无讨论 → generate_minutes 短路，不触发 LLM）→ 建决议 → 真人确认 →
决议转任务（task_type=resolution_execution，creator=真人）→ 该草稿任务出现在桌面
`my_tasks` 投影（status=created，真人可编辑/驳回，不自动对外）。

红线：未经真人确认的决议不可转任务（RuleViolation）；转出的任务是草稿，不外发。
"""

from collections.abc import AsyncGenerator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.contexts.business.meeting_management.entrypoints import operations as meeting
from app.contexts.business.work_desktop import public as work_desktop
from app.contexts.shared_kernel import RuleViolation
from app.models import Base
from app.models.system import SysUser


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


async def test_closed_meeting_resolution_becomes_desktop_draft_task(
    db: AsyncSession,
) -> None:
    manager = SysUser(username="mgr", password_hash="x", role_code="admin")
    db.add(manager)
    await db.commit()

    m = await meeting.create_meeting(db, title="季度决策会", creator_id=manager.id)
    await meeting.set_status(db, m.id, "closed")  # 无讨论 → 纪要短路，离线可跑

    res = await meeting.create_resolution(db, m.id, content="推进 X 项目立项")

    # 红线：未经真人确认不可转任务
    with pytest.raises(RuleViolation):
        await meeting.resolution_to_task(db, res.id, creator_id=manager.id)

    await db.refresh(manager)  # 内层 commit 使其过期，刷新后再读标量属性
    confirmed = await meeting.confirm_resolution(
        db, res.id, principal=meeting.principal_from_user(manager)
    )
    assert confirmed.is_confirmed is True

    task = await meeting.resolution_to_task(db, res.id, creator_id=manager.id)
    assert task.task_type == "resolution_execution"

    desk = await work_desktop.get_desktop(db, _principal(manager))
    mine = {t["id"]: t for t in desk["my_tasks"]}
    assert str(task.id) in mine  # 草稿任务进入本人桌面
    assert mine[str(task.id)]["status"] == "created"  # 草稿态，真人可编辑/驳回
