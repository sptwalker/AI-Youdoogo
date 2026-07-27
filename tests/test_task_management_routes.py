"""Task Management route characterization after Context migration."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from langchain_core.messages import AIMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api import deps
from app.contexts.foundations.model_gateway import public as _mg_public
from app.core.database import get_db
from app.main import app
from app.models import Base
from app.models.agent import AgentRole
from app.models.audit_log import AuditLog
from app.models.system import SysDepartment, SysUser
from app.models.task import TaskCard, TaskCardLog
from app.models.workflow import OUTBOX_PENDING, STEP_SUCCEEDED, OutboxEvent, WorkflowStep
from app.services import workflow_service
from app.services.orchestration_service import PlanStep, is_red_line


class _FakeLLM:
    async def ainvoke(self, messages: list, **kwargs: object) -> AIMessage:
        return AIMessage(content="执行完成")


@pytest.fixture
async def task_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncGenerator[tuple[AsyncClient, dict[str, Any]], None]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'tasks.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    department = SysDepartment(name="研发", code=f"d-{uuid.uuid4().hex[:6]}")
    other_department = SysDepartment(name="市场", code=f"m-{uuid.uuid4().hex[:6]}")
    async with factory() as session:
        session.add_all([department, other_department])
        await session.commit()
        member = SysUser(
            username="task-member",
            password_hash="x",
            role_code="member",
            department_id=department.id,
        )
        peer = SysUser(
            username="task-peer",
            password_hash="x",
            role_code="member",
            department_id=department.id,
        )
        outsider = SysUser(
            username="task-outsider",
            password_hash="x",
            role_code="member",
            department_id=other_department.id,
        )
        admin = SysUser(username="task-admin", password_hash="x", role_code="admin")
        role = AgentRole(
            name="任务执行AI",
            prompt_template="完成任务",
            model_role="daily",
            tools=["none"],
        )
        session.add_all([member, peer, outsider, admin, role])
        await session.commit()
        mine = TaskCard(
            title="我的任务",
            task_type="manual",
            creator_id=member.id,
        )
        department_task = TaskCard(
            title="部门任务",
            task_type="manual",
            creator_id=peer.id,
            department_id=department.id,
        )
        hidden = TaskCard(
            title="不可见任务",
            task_type="manual",
            creator_id=outsider.id,
            department_id=other_department.id,
        )
        reported = TaskCard(
            title="待验收任务",
            task_type="manual",
            creator_id=member.id,
            status="reported",
        )
        runnable = TaskCard(
            title="自动执行任务",
            task_type="analysis",
            creator_id=member.id,
            assignee_agent_id=role.id,
            payload={"scope": "A"},
        )
        session.add_all([mine, department_task, hidden, reported, runnable])
        await session.commit()

    actor: dict[str, SysUser] = {"user": member}

    async def _override_db() -> AsyncGenerator[AsyncSession, None]:
        async with factory() as session:
            yield session

    async def _current_user() -> SysUser:
        return actor["user"]

    monkeypatch.setattr(_mg_public, "get_llm_for_role", lambda *args, **kwargs: _FakeLLM())
    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[deps.get_current_user] = _current_user
    state: dict[str, Any] = {
        "factory": factory,
        "actor": actor,
        "users": {"member": member, "admin": admin},
        "ids": {
            "mine": mine.id,
            "department": department_task.id,
            "hidden": hidden.id,
            "reported": reported.id,
            "runnable": runnable.id,
        },
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, state
    app.dependency_overrides.clear()
    await engine.dispose()


async def test_create_list_and_detail_preserve_visibility_and_envelope(
    task_client: tuple[AsyncClient, dict[str, Any]],
) -> None:
    client, state = task_client
    created = await client.post(
        "/api/v1/tasks",
        json={"title": "新任务", "task_type": "analysis", "payload": {"x": 1}},
    )
    assert created.status_code == 200
    assert created.json()["code"] == 0
    assert created.json()["data"]["status"] == "created"

    listed = await client.get("/api/v1/tasks")
    titles = {item["title"] for item in listed.json()["data"]}
    assert {"我的任务", "部门任务", "新任务"} <= titles
    assert "不可见任务" not in titles

    detail = await client.get(f"/api/v1/tasks/{state['ids']['mine']}")
    hidden = await client.get(f"/api/v1/tasks/{state['ids']['hidden']}")
    assert detail.status_code == 200
    assert detail.json()["data"]["task"]["title"] == "我的任务"
    assert hidden.status_code == 404


async def test_decompose_and_accept_write_logs_and_audit(
    task_client: tuple[AsyncClient, dict[str, Any]],
) -> None:
    client, state = task_client
    decomposed = await client.post(
        f"/api/v1/tasks/{state['ids']['mine']}/decompose",
        json={"subtasks": [{"title": "子任务一"}, {"title": "子任务二"}]},
    )
    assert decomposed.status_code == 200
    assert [item["title"] for item in decomposed.json()["data"]] == ["子任务一", "子任务二"]

    accepted = await client.post(
        f"/api/v1/tasks/{state['ids']['reported']}/transition",
        json={"to_status": "accepted", "note": "验收通过"},
    )
    assert accepted.status_code == 200
    assert accepted.json()["data"]["status"] == "accepted"

    async with state["factory"]() as session:
        logs = list(
            (
                await session.execute(
                    select(TaskCardLog).where(TaskCardLog.task_id == state["ids"]["reported"])
                )
            ).scalars()
        )
        audit = (
            await session.execute(select(AuditLog).where(AuditLog.action == "task.accepted"))
        ).scalar_one()
    assert logs[-1].to_status == "accepted" and logs[-1].note == "验收通过"
    assert audit.target_id == state["ids"]["reported"]


async def test_run_endpoint_drives_assigned_task_to_reported(
    task_client: tuple[AsyncClient, dict[str, Any]],
) -> None:
    client, state = task_client
    response = await client.post(f"/api/v1/tasks/{state['ids']['runnable']}/run")

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "reported"
    assert "执行完成" in response.json()["data"]["result_content"]
    async with state["factory"]() as session:
        logs = list(
            (
                await session.execute(
                    select(TaskCardLog)
                    .where(TaskCardLog.task_id == state["ids"]["runnable"])
                    .order_by(TaskCardLog.create_time)
                )
            ).scalars()
        )
    assert [log.to_status for log in logs] == ["dispatched", "executing", "reported"]


async def test_accepting_durable_step_records_decision_and_resume_outbox(
    task_client: tuple[AsyncClient, dict[str, Any]],
) -> None:
    client, state = task_client
    state["actor"]["user"] = state["users"]["admin"]
    async with state["factory"]() as session:
        admin = await session.get(SysUser, state["users"]["admin"].id)
        assert admin is not None
        run = await workflow_service.create_workflow(
            session,
            request="先审批再交付",
            title="持久化编排",
            creator_id=admin.id,
            assignee_agent_id=None,
            steps=[
                PlanStep(0, "审批", "notify", "审批", []),
                PlanStep(1, "交付", "deliver", "交付", [0]),
            ],
            is_red_line=is_red_line,
        )
        await session.commit()
        first = (await workflow_service.list_steps(session, run.id))[0]
        claimed = await workflow_service.claim_step(
            session, first.id, worker_id="test", lease_seconds=60
        )
        assert claimed is not None
        assert await workflow_service.complete_step(
            session,
            claimed,
            worker_id="test",
            output_data={},
            result_content="待人工审批",
            succeeded=True,
        )
        await session.commit()
        task_id = first.task_card_id
    assert task_id is not None

    accepted = await client.post(
        f"/api/v1/tasks/{task_id}/transition",
        json={"to_status": "accepted", "note": "真人验收"},
    )
    assert accepted.status_code == 200

    async with state["factory"]() as session:
        step = await session.get(WorkflowStep, first.id)
        outbox = list(
            (
                await session.execute(
                    select(OutboxEvent).where(
                        OutboxEvent.status == OUTBOX_PENDING,
                        OutboxEvent.event_type.in_(
                            ("task.decision-recorded.v1", "workflow.advance")
                        ),
                    )
                )
            ).scalars()
        )
    assert step is not None and step.status == STEP_SUCCEEDED
    assert {event.event_type for event in outbox} == {
        "task.decision-recorded.v1",
        "workflow.advance",
    }
