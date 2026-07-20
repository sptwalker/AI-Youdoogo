"""PostgreSQL outbox 驱动的持久化工作流 worker。"""

from __future__ import annotations

import asyncio
import logging
import socket
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import run_agent
from app.agents.contracts import ExecutionContext
from app.core.config import get_settings
from app.core.database import async_session_factory
from app.models.agent import AgentRole
from app.models.workflow import (
    RUN_CANCELLED,
    RUN_FAILED,
    RUN_SUCCEEDED,
    RUN_WAITING_HUMAN,
    STEP_FAILED,
    STEP_RUNNING,
    STEP_WAITING_HUMAN,
    OutboxEvent,
    WorkflowStep,
)
from app.services import outbox_service, workflow_service

logger = logging.getLogger(__name__)

_worker_task: asyncio.Task[None] | None = None
_stop_event: asyncio.Event | None = None


def _worker_id() -> str:
    return f"{socket.gethostname()}:{uuid.uuid4().hex[:12]}"


def _step_message(step: WorkflowStep) -> str:
    """把持久化步骤及上游结构化产出渲染为 Agent 输入。"""
    parts = [f"任务：{step.title}", f"要求：{step.instruction}"]
    data = step.input_data or {}
    datasets = data.get("datasets") or []
    if datasets:
        parts.append("\n上游步骤已取得以下结构化数据，请只依据真实数据继续：")
        for dataset in datasets:
            parts.append(str(dataset)[:12000])
    artifacts = data.get("artifacts") or []
    if artifacts:
        names = "、".join(str(item.get("file_name", "")) for item in artifacts)
        parts.append(f"\n上游文件引用：{names}")
    parts.append("\n请完成本步骤；需要数据、咨询或交付时使用已启用技能。")
    return "\n".join(parts)


async def _lease_heartbeat(
    stop: asyncio.Event,
    *,
    step_id: uuid.UUID,
    attempt: int,
    worker_id: str,
    lease_seconds: int,
) -> None:
    """长 LLM/工具调用期间使用独立短会话续租，避免健康 worker 被误回收。"""
    interval = max(1.0, lease_seconds / 3)
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
            return
        except TimeoutError:
            pass
        async with async_session_factory() as heartbeat_db:
            renewed = await workflow_service.renew_step_lease(
                heartbeat_db,
                step_id,
                worker_id=worker_id,
                attempt=attempt,
                lease_seconds=lease_seconds,
            )
            if not renewed:
                await heartbeat_db.rollback()
                logger.warning("workflow step 续租失败 step=%s attempt=%s", step_id, attempt)
                return
            await heartbeat_db.commit()


async def _enqueue_ready_steps(db: AsyncSession, workflow_id: uuid.UUID) -> int:
    run = await workflow_service.get_run(db, workflow_id)
    await workflow_service.refresh_run_status(db, run)
    if run.status in (RUN_SUCCEEDED, RUN_FAILED, RUN_CANCELLED, RUN_WAITING_HUMAN):
        return 0
    steps = await workflow_service.list_steps(db, workflow_id)
    ready = workflow_service.ready_steps(steps)
    for step in ready:
        await outbox_service.enqueue(
            db,
            aggregate_type="workflow_step",
            aggregate_id=step.id,
            event_type="workflow.step.execute",
            dedupe_key=f"workflow-step:{step.id}:execute:v{step.version}",
            payload={
                "workflow_run_id": str(workflow_id),
                "workflow_step_id": str(step.id),
                "trace_id": str(run.trace_id),
            },
        )
    return len(ready)


async def _execute_step(db: AsyncSession, event: OutboxEvent, worker_id: str) -> None:
    settings = get_settings()
    raw_step_id = event.payload.get("workflow_step_id")
    if not raw_step_id:
        raise ValueError("workflow.step.execute 缺少 workflow_step_id")
    step_id = uuid.UUID(str(raw_step_id))
    claimed = await workflow_service.claim_step(
        db,
        step_id,
        worker_id=worker_id,
        lease_seconds=settings.workflow_step_lease_seconds,
    )
    if claimed is None:
        current = await db.get(WorkflowStep, step_id)
        # outbox 租约可能先于长步骤租约过期；事件可安全完成，步骤由原 worker 继续并续租。
        if current is not None and current.status == STEP_RUNNING:
            logger.info("步骤已有有效执行租约，跳过重复事件 step=%s", step_id)
        return
    await db.commit()  # 租约必须在外部 LLM/技能调用前可见

    run = await workflow_service.get_run(db, claimed.workflow_run_id)
    role = (
        await db.get(AgentRole, claimed.assignee_agent_id)
        if claimed.assignee_agent_id is not None
        else None
    )
    context = ExecutionContext(
        workflow_run_id=run.id,
        workflow_step_id=claimed.id,
        attempt=claimed.attempt,
        trace_id=run.trace_id,
        # 副作用 key 跨 attempt 稳定；attempt 单独落 trace，崩溃重试复用同一文件/请求。
        idempotency_prefix=f"{run.id}:{claimed.id}:logical",
        user_id=run.creator_id,
        user_intent=run.request_text,
        agent_runner=run_agent,
    )
    if role is None or not role.is_active:
        ok = await workflow_service.complete_step(
            db,
            claimed,
            worker_id=worker_id,
            output_data={},
            result_content="步骤无可用执行者",
            succeeded=False,
            error="步骤无可用执行者",
        )
        if not ok:
            raise RuntimeError("步骤失败状态写入被并发覆盖")
        await db.commit()
        return

    heartbeat_stop = asyncio.Event()
    heartbeat = asyncio.create_task(
        _lease_heartbeat(
            heartbeat_stop,
            step_id=claimed.id,
            attempt=claimed.attempt,
            worker_id=worker_id,
            lease_seconds=settings.workflow_step_lease_seconds,
        ),
        name=f"workflow-step-heartbeat-{claimed.id}",
    )
    try:
        record = await run_agent(
            db,
            role,
            task_type=claimed.skill,
            input_summary=f"持久化步骤：{claimed.title[:40]}",
            user_message=_step_message(claimed),
            user_id=run.creator_id,
            use_knowledge=True,
            execution_context=context,
        )
        from app.agents import skills

        text = record.output_content or record.error_msg or "（无产出）"
        skill_result = await skills.execute_all(
            db,
            role,
            text,
            user_id=run.creator_id,
            user_intent=run.request_text,
            execution_context=context,
        )
    finally:
        heartbeat_stop.set()
        await asyncio.gather(heartbeat, return_exceptions=True)
    for consulted, consult_record in skill_result.consult_replies:
        answer = consult_record.output_content or consult_record.error_msg or "（无产出）"
        text += f"\n\n---\n【{consulted.name} 答复】\n{answer}"
    text = skills.fold_notes(text, skill_result)
    succeeded = record.status != "failed"
    output_data: dict[str, Any] = {
        "agent_task_record_id": str(record.id),
        "datasets": skill_result.datasets,
        "artifacts": skill_result.artifacts,
        "tool_execution_ids": [str(item) for item in skill_result.tool_execution_ids],
    }
    ok = await workflow_service.complete_step(
        db,
        claimed,
        worker_id=worker_id,
        output_data=output_data,
        result_content=text,
        succeeded=succeeded,
        error=record.error_msg,
    )
    if not ok:
        raise RuntimeError("步骤完成状态写入被并发覆盖")
    if succeeded:
        await workflow_service.pipe_outputs(
            db,
            claimed,
            datasets=skill_result.datasets,
            artifacts=skill_result.artifacts,
        )
    if claimed.status not in (STEP_WAITING_HUMAN, STEP_FAILED):
        await outbox_service.enqueue(
            db,
            aggregate_type="workflow",
            aggregate_id=run.id,
            event_type="workflow.advance",
            dedupe_key=f"workflow:{run.id}:advance:{claimed.id}:attempt:{claimed.attempt}",
            payload={"workflow_run_id": str(run.id), "trace_id": str(run.trace_id)},
        )
    await db.commit()


async def handle_event(db: AsyncSession, event: OutboxEvent, *, worker_id: str) -> None:
    """处理一条已抢占事件。"""
    if event.event_type == "workflow.advance":
        workflow_id = uuid.UUID(str(event.payload["workflow_run_id"]))
        await _enqueue_ready_steps(db, workflow_id)
        await db.commit()
        return
    if event.event_type == "workflow.step.execute":
        await _execute_step(db, event, worker_id)
        return
    raise ValueError(f"未知 outbox event_type：{event.event_type}")


async def process_one(db: AsyncSession, *, worker_id: str) -> bool:
    """抢占并处理一条事件；供后台循环和单测复用。"""
    settings = get_settings()
    event = await outbox_service.claim_next(
        db,
        worker_id=worker_id,
        lease_seconds=settings.workflow_event_lease_seconds,
    )
    if event is None:
        await db.rollback()
        return False
    await db.commit()
    try:
        await handle_event(db, event, worker_id=worker_id)
        current = await db.get(OutboxEvent, event.id)
        if current is None:
            raise RuntimeError("outbox 事件丢失")
        await outbox_service.complete(db, current, worker_id=worker_id)
        await db.commit()
    except Exception as exc:
        await db.rollback()
        current = await db.get(OutboxEvent, event.id)
        if current is not None:
            terminal = current.attempts >= current.max_attempts
            await outbox_service.fail(
                db,
                current,
                worker_id=worker_id,
                error=str(exc),
                retry_delay_seconds=settings.workflow_retry_delay_seconds,
            )
            if terminal:
                await workflow_service.fail_from_outbox(db, current, error=str(exc))
            await db.commit()
        raise
    return True


async def run_once(*, worker_id: str | None = None) -> bool:
    """使用独立会话处理一条事件。"""
    async with async_session_factory() as db:
        return await process_one(db, worker_id=worker_id or _worker_id())


async def run_forever(stop: asyncio.Event, *, worker_id: str) -> None:
    """后台轮询循环；单次故障隔离，不阻断应用。"""
    poll = max(0.1, get_settings().workflow_worker_poll_seconds)
    while not stop.is_set():
        worked = False
        try:
            worked = await run_once(worker_id=worker_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("workflow worker 处理失败", exc_info=True)
        if worked:
            continue
        try:
            await asyncio.wait_for(stop.wait(), timeout=poll)
        except TimeoutError:
            pass


def start_background_worker() -> asyncio.Task[None] | None:
    """启动应用内 worker；多 Web 进程由租约保证安全。"""
    global _stop_event, _worker_task
    if not get_settings().workflow_worker_enabled:
        return None
    if _worker_task is not None and not _worker_task.done():
        return _worker_task
    _stop_event = asyncio.Event()
    _worker_task = asyncio.create_task(
        run_forever(_stop_event, worker_id=_worker_id()), name="workflow-outbox-worker"
    )
    return _worker_task


async def stop_background_worker() -> None:
    """通知 worker 停止并等待当前循环退出。"""
    global _stop_event, _worker_task
    if _worker_task is None:
        return
    if _stop_event is not None:
        _stop_event.set()
    try:
        await asyncio.wait_for(_worker_task, timeout=5)
    except TimeoutError:
        _worker_task.cancel()
        await asyncio.gather(_worker_task, return_exceptions=True)
    finally:
        _worker_task = None
        _stop_event = None
