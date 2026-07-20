"""持久化 workflow/outbox runtime 的事务、租约、恢复与 worker 回归测试。"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import Base
from app.models.agent import AgentRole, AgentTaskRecord
from app.models.system import SysUser
from app.models.task import TaskCard
from app.models.workflow import (
    OUTBOX_DONE,
    OUTBOX_PENDING,
    RUN_FAILED,
    RUN_SUCCEEDED,
    RUN_WAITING_HUMAN,
    STEP_RUNNING,
    STEP_SUCCEEDED,
    STEP_WAITING_HUMAN,
    OutboxEvent,
    WorkflowEvent,
    WorkflowRun,
    WorkflowStep,
)
from app.services import outbox_service, task_flow, task_service, workflow_service, workflow_worker
from app.services.orchestration_service import PlanStep, is_red_line


@pytest.fixture
async def maker(
    tmp_path: Path,
) -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    db_path = tmp_path / "durable.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def _seed(db: AsyncSession, *, with_agent: bool = False) -> tuple[SysUser, AgentRole | None]:
    user = SysUser(username=f"u-{uuid.uuid4().hex[:8]}", password_hash="x", role_code="admin")
    role = (
        AgentRole(
            name=f"agent-{uuid.uuid4().hex[:8]}",
            prompt_template="只执行测试任务",
            model_role="daily",
            tools=["none"],
        )
        if with_agent
        else None
    )
    db.add(user)
    if role is not None:
        db.add(role)
    await db.commit()
    return user, role


def _steps(*, first_red_line: bool = False) -> list[PlanStep]:
    return [
        PlanStep(
            no=0,
            title="第一步",
            skill="notify" if first_red_line else "data_query",
            instruction="执行第一步",
            depends_on=[],
        ),
        PlanStep(
            no=1,
            title="第二步",
            skill="deliver",
            instruction="执行第二步",
            depends_on=[0],
        ),
    ]


async def _create_run(
    db: AsyncSession,
    user: SysUser,
    *,
    role: AgentRole | None = None,
    first_red_line: bool = False,
) -> WorkflowRun:
    run = await workflow_service.create_workflow(
        db,
        request="先执行第一步再执行第二步",
        title="durable workflow",
        creator_id=user.id,
        assignee_agent_id=role.id if role else None,
        steps=_steps(first_red_line=first_red_line),
        is_red_line=is_red_line,
    )
    await db.commit()
    return run


async def test_atomic_creation_rolls_back_all_mirrors(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    async with maker() as db:
        user, _ = await _seed(db)
        invalid = _steps()
        invalid[1].depends_on = [99]
        with pytest.raises(KeyError):
            await workflow_service.create_workflow(
                db,
                request="invalid",
                title="invalid",
                creator_id=user.id,
                assignee_agent_id=None,
                steps=invalid,
                is_red_line=is_red_line,
            )
        await db.rollback()
        for model in (WorkflowRun, WorkflowStep, WorkflowEvent, OutboxEvent, TaskCard):
            count = (await db.execute(select(func.count()).select_from(model))).scalar_one()
            assert count == 0


async def test_versioned_claim_allows_only_one_stale_worker(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    async with maker() as setup:
        user, _ = await _seed(setup)
        run = await _create_run(setup, user)
        step_id = (await workflow_service.list_steps(setup, run.id))[0].id

    async with maker() as first, maker() as second:
        await first.get(WorkflowStep, step_id)
        await second.get(WorkflowStep, step_id)
        won = await workflow_service.claim_step(
            first, step_id, worker_id="worker-a", lease_seconds=60
        )
        assert won is not None
        await first.commit()
        lost = await workflow_service.claim_step(
            second, step_id, worker_id="worker-b", lease_seconds=60
        )
        assert lost is None
        await second.rollback()


async def test_parent_finalizes_after_all_steps_succeed(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    async with maker() as db:
        user, _ = await _seed(db)
        run = await _create_run(db, user)
        steps = await workflow_service.list_steps(db, run.id)
        for step in steps:
            claimed = await workflow_service.claim_step(
                db, step.id, worker_id="worker", lease_seconds=60
            )
            assert claimed is not None
            assert await workflow_service.complete_step(
                db,
                claimed,
                worker_id="worker",
                output_data={},
                result_content="ok",
                succeeded=True,
            )
            await db.commit()
        await db.refresh(run)
        parent = await task_service.get_task(db, run.parent_task_id)  # type: ignore[arg-type]
        assert run.status == RUN_SUCCEEDED
        assert parent.status == task_flow.ACCEPTED


async def test_expired_lease_is_reclaimed_as_new_attempt(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    async with maker() as db:
        user, _ = await _seed(db)
        run = await _create_run(db, user)
        step = (await workflow_service.list_steps(db, run.id))[0]
        first = await workflow_service.claim_step(
            db, step.id, worker_id="worker-a", lease_seconds=60
        )
        assert first is not None and first.attempt == 1
        await db.commit()
        first.lease_until = outbox_service.utcnow() - timedelta(seconds=1)
        await db.commit()
        reclaimed = await workflow_service.claim_step(
            db, step.id, worker_id="worker-b", lease_seconds=60
        )
        assert reclaimed is not None
        assert reclaimed.attempt == 2 and reclaimed.lease_owner == "worker-b"
        events = list(
            (
                await db.execute(
                    select(WorkflowEvent).where(
                        WorkflowEvent.workflow_step_id == step.id,
                        WorkflowEvent.event_type == "step.reclaimed",
                    )
                )
            ).scalars()
        )
        assert len(events) == 1 and events[0].attempt == 2


async def test_human_accept_enqueues_resume_without_running_downstream(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    async with maker() as db:
        user, _ = await _seed(db)
        run = await _create_run(db, user, first_red_line=True)
        first, second = await workflow_service.list_steps(db, run.id)
        claimed = await workflow_service.claim_step(
            db, first.id, worker_id="worker", lease_seconds=60
        )
        assert claimed is not None
        assert await workflow_service.complete_step(
            db,
            claimed,
            worker_id="worker",
            output_data={},
            result_content="draft",
            succeeded=True,
        )
        await db.commit()
        await db.refresh(run)
        assert first.status == STEP_WAITING_HUMAN and run.status == RUN_WAITING_HUMAN
        card = await task_service.get_task(db, first.task_card_id)  # type: ignore[arg-type]
        await task_service.transition(
            db, card.id, task_flow.ACCEPTED, operator_id=user.id, note="真人验收"
        )
        resumed = await workflow_service.accept_human_step(db, card.id, operator_id=user.id)
        assert resumed is not None
        await db.commit()
        await db.refresh(second)
        assert first.status == STEP_SUCCEEDED
        assert second.status != STEP_RUNNING
        pending_resume = (
            await db.execute(
                select(OutboxEvent).where(
                    OutboxEvent.event_type == "workflow.advance",
                    OutboxEvent.status == OUTBOX_PENDING,
                    OutboxEvent.dedupe_key.contains("resume"),
                )
            )
        ).scalar_one()
        assert pending_resume.aggregate_id == run.id


async def test_outbox_claim_retry_and_complete(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    async with maker() as db:
        event = await outbox_service.enqueue(
            db,
            aggregate_type="test",
            aggregate_id=uuid.uuid4(),
            event_type="test.event",
            dedupe_key=f"test:{uuid.uuid4()}",
            max_attempts=3,
        )
        event_id = event.id
        await db.commit()
        claimed = await outbox_service.claim_next(db, worker_id="a", lease_seconds=60)
        assert claimed is not None and claimed.attempts == 1
        await db.commit()
        assert await outbox_service.claim_next(db, worker_id="b", lease_seconds=60) is None
        await db.rollback()
        current = await db.get(OutboxEvent, event_id)
        assert current is not None
        assert await outbox_service.fail(
            db, current, worker_id="a", error="temporary", retry_delay_seconds=0
        )
        await db.commit()
        await db.refresh(current)
        assert current.status == OUTBOX_PENDING
        claimed_again = await outbox_service.claim_next(db, worker_id="b", lease_seconds=60)
        assert claimed_again is not None and claimed_again.attempts == 2
        assert await outbox_service.complete(db, claimed_again, worker_id="b")
        await db.commit()
        await db.refresh(claimed_again)
        assert claimed_again.status == OUTBOX_DONE


async def test_worker_drives_full_dag(
    maker: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    async with maker() as db:
        user, role = await _seed(db, with_agent=True)
        assert role is not None
        run = await _create_run(db, user, role=role)

        async def _fake_run_agent(
            _db: AsyncSession, target: AgentRole, **kwargs: object
        ) -> AgentTaskRecord:
            return AgentTaskRecord(
                id=uuid.uuid4(),
                agent_role_id=target.id,
                task_type=str(kwargs.get("task_type", "test")),
                output_content="步骤完成",
                status="success",
            )

        monkeypatch.setattr(workflow_worker, "run_agent", _fake_run_agent)
        for _ in range(10):
            if not await workflow_worker.process_one(db, worker_id="test-worker"):
                break
        await db.refresh(run)
        steps = await workflow_service.list_steps(db, run.id)
        assert run.status == RUN_SUCCEEDED
        assert all(step.status == STEP_SUCCEEDED for step in steps)


async def test_worker_terminal_outbox_failure_marks_workflow_failed(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    async with maker() as db:
        user, _ = await _seed(db)
        run = await _create_run(db, user)
        await outbox_service.enqueue(
            db,
            aggregate_type="workflow",
            aggregate_id=run.id,
            event_type="unknown.event",
            dedupe_key=f"unknown:{uuid.uuid4()}",
            payload={"workflow_run_id": str(run.id)},
            max_attempts=1,
        )
        await db.commit()
        assert await workflow_worker.process_one(db, worker_id="terminal-worker")
        with pytest.raises(ValueError, match="未知 outbox"):
            await workflow_worker.process_one(db, worker_id="terminal-worker")
        await db.refresh(run)
        assert run.status == RUN_FAILED and run.error_msg
