"""调度中枢单测：分配智能体的任务卡自动驱动到「已汇报」（假模型 + 内存 SQLite）。"""

import uuid
from collections.abc import AsyncGenerator

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.agents import base, scheduler
from app.contexts.shared_kernel import ApplicationError
from app.models import Base
from app.models.agent import AgentRole
from app.models.system import SysUser
from app.services import task_flow, task_service


class _FakeLLM:
    async def ainvoke(self, messages: list, **kwargs: object) -> AIMessage:
        return AIMessage(content="任务执行结果：已完成分析。")


@pytest.fixture
async def ctx() -> AsyncGenerator[tuple[AsyncSession, uuid.UUID, uuid.UUID], None]:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        user = SysUser(username="boss", password_hash="x", role_code="admin")
        role = AgentRole(name="运营AI总监", prompt_template="你是运营AI总监。", model_role="daily")
        session.add_all([user, role])
        await session.commit()
        yield session, user.id, role.id
    await engine.dispose()


async def test_run_task_drives_to_reported(
    ctx: tuple[AsyncSession, uuid.UUID, uuid.UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    session, uid, role_id = ctx
    monkeypatch.setattr(base, "get_llm_for_role", lambda *a, **k: _FakeLLM())
    task = await task_service.create_task(
        session, title="竞品分析", task_type="analysis", creator_id=uid,
        assignee_agent_id=role_id, payload={"scope": "产品A"},
    )
    result = await scheduler.run_task(session, task.id, operator_id=uid)
    assert result.status == task_flow.REPORTED
    assert result.result_content and "已完成" in result.result_content
    # 全流转留痕
    logs = await task_service.list_logs(session, task.id)
    assert [x.to_status for x in logs] == [
        task_flow.CREATED, task_flow.DISPATCHED, task_flow.EXECUTING, task_flow.REPORTED,
    ]
    # 真人验收闭环
    accepted = await task_service.transition(
        session, task.id, task_flow.ACCEPTED, operator_id=uid
    )
    assert accepted.status == task_flow.ACCEPTED


async def test_run_task_without_assignee_rejected(
    ctx: tuple[AsyncSession, uuid.UUID, uuid.UUID],
) -> None:
    session, uid, _ = ctx
    task = await task_service.create_task(session, title="T", task_type="x", creator_id=uid)
    with pytest.raises(ApplicationError, match="未分配智能体"):
        await scheduler.run_task(session, task.id, operator_id=uid)
