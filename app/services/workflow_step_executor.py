"""External Agent/skill execution with short durable state transactions."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.contracts import AgentRunner, ExecutionContext
from app.core.config import get_settings
from app.core.database import async_session_factory
from app.models.agent import AgentRole
from app.models.workflow import (
    STEP_FAILED,
    STEP_WAITING_HUMAN,
    OutboxEvent,
    WorkflowStep,
)
from app.services import outbox_service, workflow_service


class StepExecutionDisposition:
    """事件处理完成或因有效步骤租约而延迟。"""

    __slots__ = ("kind", "retry_at", "reason")

    def __init__(
        self,
        kind: Literal["complete", "defer"],
        *,
        retry_at: Any = None,
        reason: str | None = None,
    ) -> None:
        self.kind = kind
        self.retry_at = retry_at
        self.reason = reason

    @classmethod
    def complete(cls) -> StepExecutionDisposition:
        return cls("complete")

    @classmethod
    def defer(cls, retry_at: Any, *, reason: str) -> StepExecutionDisposition:
        return cls("defer", retry_at=retry_at, reason=reason)


def step_message(step: WorkflowStep) -> str:
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


async def lease_heartbeat(
    stop: asyncio.Event,
    *,
    step_id: uuid.UUID,
    attempt: int,
    worker_id: str,
    lease_seconds: int,
) -> None:
    """长 LLM/工具调用期间使用独立短会话续租。"""
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
                return
            await heartbeat_db.commit()


async def execute_step(
    db: AsyncSession,
    event: OutboxEvent,
    *,
    worker_id: str,
    agent_runner: AgentRunner,
) -> StepExecutionDisposition:
    settings = get_settings()
    raw_step_id = event.payload.get("workflow_step_id")
    if not raw_step_id:
        raise ValueError("workflow.step.execute 缺少 workflow_step_id")
    step_id = uuid.UUID(str(raw_step_id))
    claim = await workflow_service.claim_step_result(
        db,
        step_id,
        worker_id=worker_id,
        lease_seconds=settings.workflow_step_lease_seconds,
    )
    if claim.status == "busy":
        return StepExecutionDisposition.defer(
            claim.retry_at or outbox_service.utcnow(),
            reason=f"步骤仍由 {claim.step.lease_owner if claim.step else 'other worker'} 持有租约",
        )
    if claim.status == "terminal" or claim.step is None:
        return StepExecutionDisposition.complete()
    claimed = claim.step
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
        idempotency_prefix=f"{run.id}:{claimed.id}:logical",
        user_id=run.creator_id,
        user_intent=run.request_text,
        agent_runner=agent_runner,
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
        return StepExecutionDisposition.complete()

    heartbeat_stop = asyncio.Event()
    heartbeat = asyncio.create_task(
        lease_heartbeat(
            heartbeat_stop,
            step_id=claimed.id,
            attempt=claimed.attempt,
            worker_id=worker_id,
            lease_seconds=settings.workflow_step_lease_seconds,
        ),
        name=f"workflow-step-heartbeat-{claimed.id}",
    )
    try:
        record = await agent_runner(
            db,
            role,
            task_type=claimed.skill,
            input_summary=f"持久化步骤：{claimed.title[:40]}",
            user_message=step_message(claimed),
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
    return StepExecutionDisposition.complete()
