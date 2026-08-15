"""B3.2 会前推送钩子红线：自我提醒不停点（建本人草稿 Task）；对外提醒必停 waiting_human。"""

from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.bootstrap import pre_meeting_reminder as reminder
from app.contexts.business.work_desktop import public as work_desktop
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


# ── 纯函数：到点判定 ──────────────────────────────────────
def test_is_due_within_lead_window() -> None:
    start = datetime(2026, 8, 17, 10, tzinfo=UTC)
    assert reminder.is_due(start, start - timedelta(minutes=10)) is True
    assert reminder.is_due(start, start - timedelta(minutes=20)) is False  # 太早
    assert reminder.is_due(start, start) is False  # 已开始不再提醒


def test_outbound_requires_human_self_does_not() -> None:
    assert reminder.reminder_requires_human_review(is_outbound=True) is True
    assert reminder.reminder_requires_human_review(is_outbound=False) is False


# ── 自我提醒：建本人草稿 Task 进收件箱，不停点 ──────────────
async def test_self_reminder_creates_desktop_draft_without_stop(db: AsyncSession) -> None:
    u = SysUser(username="me", password_hash="x", role_code="member")
    db.add(u)
    await db.commit()

    out = await reminder.push_reminder(
        db, owner_id=u.id, meeting_title="周会", is_outbound=False
    )
    assert out["stopped"] is False and out["task"] is not None
    await db.commit()

    desk = await work_desktop.get_desktop(
        db,
        work_desktop.DesktopPrincipal(
            id=u.id, display_name=u.username, role_code=u.role_code, department_id=None
        ),
    )
    titles = [t["title"] for t in desk["my_tasks"]]
    assert "[会前提醒] 周会" in titles  # 落本人桌面


# ── 对外提醒：必停 waiting_human，不建卡不直发 ──────────────
async def test_outbound_reminder_stops_waiting_human(db: AsyncSession) -> None:
    u = SysUser(username="mgr", password_hash="x", role_code="admin")
    db.add(u)
    await db.commit()

    out = await reminder.push_reminder(
        db, owner_id=u.id, meeting_title="对外客户会", is_outbound=True
    )
    assert out["stopped"] is True  # 红线：对外必停
    assert out["task"] is None  # 不建卡、不直发
    assert out["capability"] == "feishu_notify_person"
