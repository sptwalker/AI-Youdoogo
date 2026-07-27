"""第二部门智能体复制验证：新建 agent_role（零新代码）即可被调度中枢驱动。"""

import uuid
from collections.abc import AsyncGenerator

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.agents import scheduler
from app.contexts.foundations.model_gateway import public as _mg_public
from app.contexts.shared_kernel import ApplicationError
from app.models import Base
from app.models.system import SysUser
from app.services import agent_role_service, task_flow, task_service


class _FakeLLM:
    async def ainvoke(self, messages: list, **kwargs: object) -> AIMessage:
        return AIMessage(content="销售周报：本周销量环比增长。")


@pytest.fixture
async def ctx() -> AsyncGenerator[tuple[AsyncSession, uuid.UUID], None]:
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


async def test_new_department_agent_via_config_only(
    ctx: tuple[AsyncSession, uuid.UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    """新增“销售AI总监”仅需建一行角色，任务卡即可跑通——验证边际成本=数据。"""
    session, uid = ctx
    monkeypatch.setattr(_mg_public, "get_llm_for_role", lambda *a, **k: _FakeLLM())

    role = await agent_role_service.create_agent_role(
        session,
        name="销售AI总监",
        prompt_template="你是销售部AI总监，负责销量分析与销售周报。",
        duty="销量监控、渠道分析、销售周报",
        model_role="daily",
    )
    task = await task_service.create_task(
        session, title="本周销售周报", task_type="weekly_report", creator_id=uid,
        assignee_agent_id=role.id,
    )
    result = await scheduler.run_task(session, task.id, operator_id=uid)
    assert result.status == task_flow.REPORTED
    assert result.result_content and "销售周报" in result.result_content


async def test_duplicate_role_name_rejected(ctx: tuple[AsyncSession, uuid.UUID]) -> None:
    session, _ = ctx
    await agent_role_service.create_agent_role(session, name="重复角色", prompt_template="x")
    with pytest.raises(ApplicationError, match="已存在"):
        await agent_role_service.create_agent_role(session, name="重复角色", prompt_template="y")


async def test_invalid_model_role_rejected(ctx: tuple[AsyncSession, uuid.UUID]) -> None:
    session, _ = ctx
    with pytest.raises(ApplicationError, match="model_role"):
        await agent_role_service.create_agent_role(
            session, name="X", prompt_template="p", model_role="bogus"
        )


async def test_update_toggle_active(ctx: tuple[AsyncSession, uuid.UUID]) -> None:
    session, _ = ctx
    role = await agent_role_service.create_agent_role(session, name="Y", prompt_template="p")
    updated = await agent_role_service.update_agent_role(session, role.id, is_active=False)
    assert updated.is_active is False
