"""typed skill dispatcher 的幂等、校验、追踪与去环回归。"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.agents import base, skills
from app.agents.contracts import ExecutionContext, SkillRequest
from app.agents.skill_registry import REGISTRY
from app.contexts.business.collaboration_requests.entrypoints.agent_capability import (
    CollabSkillExecutor,
)
from app.contexts.foundations.execution.deliverable_management.entrypoints.agent_capability import (
    DeliverySkillExecutor,
)
from app.contexts.foundations.integration.governed_data_query.entrypoints.agent_capability import (
    DataQuerySkillExecutor,
)
from app.contexts.foundations.model_gateway import public as _mg_public
from app.models import Base
from app.models.agent import AgentRole
from app.models.collab import CollabRequest
from app.models.deliverable import Deliverable
from app.models.llm_log import LlmCallLog
from app.models.system import DEPT_L1, SysDepartment, SysUser
from app.models.workflow import TOOL_FAILED, ToolExecution
from app.services import deliver_service, workflow_service
from app.services.orchestration_service import PlanStep, is_red_line


@pytest.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


async def _identity(db: AsyncSession, *, tools: list[str]) -> tuple[SysUser, AgentRole]:
    user = SysUser(
        username=f"u-{uuid.uuid4().hex[:8]}", password_hash="x", role_code="admin"
    )
    role = AgentRole(
        name=f"agent-{uuid.uuid4().hex[:8]}",
        prompt_template="测试",
        model_role="daily",
        tools=tools,
    )
    db.add_all([user, role])
    await db.commit()
    return user, role


_DELIVERY = (
    "【交付】名称：运营日报；格式：xlsx\n```\n"
    "| 指标 | 值 |\n| --- | --- |\n| DAU | 42 |\n```"
)


async def test_delivery_replay_reuses_record_and_object(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user, role = await _identity(db, tools=["deliver"])
    uploads: list[str] = []

    async def _put(object_name: str, _data: bytes, _content_type: str) -> str:
        uploads.append(object_name)
        return f"bucket/{object_name}"

    monkeypatch.setattr(deliver_service.storage, "put_object", _put)
    context = ExecutionContext(
        user_id=user.id,
        trace_id=uuid.uuid4(),
        attempt=1,
        idempotency_prefix="workflow:step:logical",
    )
    first = await skills.execute_all(db, role, _DELIVERY, execution_context=context)
    second = await skills.execute_all(db, role, _DELIVERY, execution_context=context)
    assert len(uploads) == 1
    assert uploads[0].startswith("deliverables/idempotent/")
    assert first.artifacts == second.artifacts
    assert len(first.tool_execution_ids) == len(second.tool_execution_ids) == 1
    deliverables = (
        await db.execute(select(func.count()).select_from(Deliverable))
    ).scalar_one()
    executions = (
        await db.execute(select(func.count()).select_from(ToolExecution))
    ).scalar_one()
    assert deliverables == executions == 1


async def test_collab_replay_creates_one_review_request(db: AsyncSession) -> None:
    user, role = await _identity(db, tools=["collab"])
    source = SysDepartment(
        name="财务部", code="fin", node_type=DEPT_L1, level=1, path=""
    )
    target = SysDepartment(
        name="运营部", code="ops", node_type=DEPT_L1, level=1, path=""
    )
    db.add_all([source, target])
    await db.commit()
    role.department_id = source.id
    await db.commit()
    text = "【发起协作】目标部门：运营部；类别：analysis；内容：复核昨日DAU"
    context = ExecutionContext(
        user_id=user.id,
        trace_id=uuid.uuid4(),
        attempt=1,
        idempotency_prefix="workflow:collab-step:logical",
    )
    first = await skills.execute_all(db, role, text, execution_context=context)
    second = await skills.execute_all(db, role, text, execution_context=context)
    count = (await db.execute(select(func.count()).select_from(CollabRequest))).scalar_one()
    execution_count = (
        await db.execute(select(func.count()).select_from(ToolExecution))
    ).scalar_one()
    assert count == 1
    assert execution_count == 1
    assert first.artifacts == second.artifacts
    assert first.artifacts[0]["collab_request_id"]
    assert len(first.tool_execution_ids) == len(second.tool_execution_ids) == 1
    assert first.tool_execution_ids == second.tool_execution_ids


async def test_invalid_or_unregistered_action_never_executes_side_effect(
    db: AsyncSession,
) -> None:
    user, role = await _identity(db, tools=["deliver"])
    dispatcher = skills.ToolDispatcher()
    context = ExecutionContext(
        user_id=user.id,
        trace_id=uuid.uuid4(),
        idempotency_prefix="workflow:invalid:logical",
    )
    invalid = await dispatcher.dispatch(
        db,
        role,
        SkillRequest(
            skill_key="deliver",
            action_index=0,
            arguments={"name": "缺正文", "format": "txt"},
        ),
        context,
    )
    rejected = await dispatcher.dispatch(
        db,
        role,
        SkillRequest(
            skill_key="approve_budget",
            action_index=1,
            arguments={"amount": 1000},
        ),
        context,
    )
    assert any("执行失败" in note for note in invalid.notes)
    assert any("未注册" in note for note in rejected.notes)
    assert (await db.execute(select(Deliverable))).first() is None
    tool = (await db.execute(select(ToolExecution))).scalar_one()
    assert tool.status == TOOL_FAILED


async def test_agent_and_llm_records_keep_workflow_trace(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user, role = await _identity(db, tools=["none"])
    run = await workflow_service.create_workflow(
        db,
        request="先分析再交付",
        title="trace test",
        creator_id=user.id,
        assignee_agent_id=role.id,
        steps=[
            PlanStep(0, "分析", "data_query", "分析", []),
            PlanStep(1, "交付", "deliver", "交付", [0]),
        ],
        is_red_line=is_red_line,
    )
    await db.commit()
    step = (await workflow_service.list_steps(db, run.id))[0]

    class _FakeLLM:
        async def ainvoke(self, _messages: list[Any]) -> AIMessage:
            return AIMessage(
                content="完成",
                response_metadata={"model_name": "fake-model"},
                usage_metadata={"input_tokens": 3, "output_tokens": 2, "total_tokens": 5},
            )

    monkeypatch.setattr(_mg_public, "get_llm_for_role", lambda *args, **kwargs: _FakeLLM())
    context = ExecutionContext(
        workflow_run_id=run.id,
        workflow_step_id=step.id,
        attempt=2,
        trace_id=run.trace_id,
        user_id=user.id,
    )
    record = await base.run_agent(
        db,
        role,
        task_type="trace_test",
        input_summary="trace",
        user_message="执行",
        user_id=user.id,
        execution_context=context,
    )
    log = (
        await db.execute(select(LlmCallLog).where(LlmCallLog.task_id == record.id))
    ).scalar_one()
    for item in (record, log):
        assert item.workflow_run_id == run.id
        assert item.workflow_step_id == step.id
        assert item.attempt_no == 2
        assert item.trace_id == run.trace_id


def test_skill_services_do_not_import_agent_base() -> None:
    root = Path(__file__).resolve().parents[1]
    for relative in (
        "app/services/collab_protocol.py",
        "app/services/query_skill.py",
        "app/services/deliver_service.py",
    ):
        source = (root / relative).read_text(encoding="utf-8")
        assert "app.agents.base" not in source


def test_data_query_registry_uses_canonical_capability_adapter() -> None:
    factory = REGISTRY["data_query"].executor_factory
    assert factory is not None
    assert isinstance(factory(), DataQuerySkillExecutor)


def test_delivery_registry_uses_canonical_capability_adapter() -> None:
    factory = REGISTRY["deliver"].executor_factory
    assert factory is not None
    assert isinstance(factory(), DeliverySkillExecutor)


def test_collaboration_registry_uses_canonical_capability_adapter() -> None:
    factory = REGISTRY["collab"].executor_factory
    assert factory is not None
    assert isinstance(factory(), CollabSkillExecutor)
