"""真人工作台 F3 单测：三队列聚合正/负向（内存 SQLite）。"""

import uuid
from collections.abc import AsyncGenerator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import Base
from app.models.meeting import MeetingResolution
from app.models.proposal import APPROVED, DRAFT, REVIEWED, ProposalCard
from app.models.task import TaskCard
from app.services import workbench_service
from app.services.task_flow import ACCEPTED, REPORTED


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


def _task(status: str) -> TaskCard:
    return TaskCard(title="t", task_type="daily_report", status=status, creator_id=uuid.uuid4())


def _proposal(code: str, status: str) -> ProposalCard:
    return ProposalCard(
        code=code, title="p", background="b", plan="pl", status=status, creator_id=uuid.uuid4()
    )


def _resolution(confirmed: bool) -> MeetingResolution:
    return MeetingResolution(meeting_id=uuid.uuid4(), content="r", is_confirmed=confirmed)


async def test_pending_collects_three_queues(session: AsyncSession) -> None:
    t, p, r = _task(REPORTED), _proposal("P1", REVIEWED), _resolution(False)
    session.add_all([t, p, r])
    await session.commit()

    result = await workbench_service.get_pending(session)
    assert result["counts"] == {"tasks": 1, "proposals": 1, "resolutions": 1}
    assert result["tasks"][0]["id"] == str(t.id)
    assert result["proposals"][0]["id"] == str(p.id)
    assert result["resolutions"][0]["id"] == str(r.id)


async def test_pending_excludes_settled(session: AsyncSession) -> None:
    """已验收任务 / 未到评审的提案 / 已确认决议 均不算待办（防查询条件写反）。"""
    session.add_all(
        [_task(ACCEPTED), _proposal("P2", DRAFT), _proposal("P3", APPROVED), _resolution(True)]
    )
    await session.commit()

    result = await workbench_service.get_pending(session)
    assert result["counts"] == {"tasks": 0, "proposals": 0, "resolutions": 0}
