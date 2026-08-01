"""Workflow-owned Outbox event preparation."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.execution.workflow_runtime.application.ports import (
    TaskProjectionPort,
)
from app.contexts.foundations.execution.workflow_runtime.infrastructure import (
    sqlalchemy_projection,
    sqlalchemy_repository,
    sqlalchemy_state,
)
from app.contexts.foundations.execution.workflow_runtime.infrastructure.step_leases import (
    claim_step_result,
)
from app.core.config import get_settings
from app.models.workflow import (
    RUN_CANCELLED,
    RUN_FAILED,
    RUN_SUCCEEDED,
    RUN_WAITING_HUMAN,
    WorkflowRun,
    WorkflowStep,
)
from app.platform.eventing.remote_step import REMOTE_SENTINEL, STEP_READY_EVENT
from app.platform.outbox.repository import enqueue


def _step_ready_payload(run: WorkflowRun, step: WorkflowStep) -> dict[str, object]:
    """据 step 列直接组装出站 payload（不读 expert 快照 → 保持 runtime 边界干净）。

    # ponytail: user_message 内联渲染 title/instruction（echo 骨架足够）；真执行器进远端时
    # 升级为 render_step_message + 上游 datasets/artifacts，并恢复 model_role/knowledge
    # 字段（docs/23 §6.3.2）。
    """
    return {
        "workflow_run_id": str(step.workflow_run_id),
        "workflow_step_id": str(step.id),
        "step_version": step.version,
        "expert_id": str(step.assignee_agent_id) if step.assignee_agent_id else None,
        "user_message": f"任务：{step.title}\n要求：{step.instruction}",
        "trace_id": str(run.trace_id),
        "correlation_id": str(step.id),
    }


async def enqueue_ready_steps(
    session: AsyncSession,
    workflow_id: uuid.UUID,
    *,
    task_projection: TaskProjectionPort,
) -> int:
    run = await sqlalchemy_repository.get_run(session, workflow_id)
    await sqlalchemy_projection.refresh_run_status(
        session, run, task_projection=task_projection
    )
    if run.status in (RUN_SUCCEEDED, RUN_FAILED, RUN_CANCELLED, RUN_WAITING_HUMAN):
        return 0
    steps = await sqlalchemy_repository.list_steps(session, workflow_id)
    ready = sqlalchemy_state.ready_steps(steps)
    settings = get_settings()
    for step in ready:
        # 远端异步分叉（docs/23 §6.3）：skill ∈ allowlist 且有属主 expert →
        # sentinel 停车 + 出站 step.ready；否则（含默认关：relay 关或 allowlist
        # 不含）走原 execute 分支，逐字不变。
        if (
            settings.event_relay_enabled
            and step.skill in settings.event_remote_step_skills
            and step.assignee_agent_id is not None
        ):
            claimed = await claim_step_result(
                session,
                step.id,
                worker_id=REMOTE_SENTINEL,
                lease_seconds=settings.event_remote_step_lease_seconds,
                task_projection=task_projection,
            )
            if claimed.status == "claimed" and claimed.step is not None:
                await enqueue(
                    session,
                    aggregate_type="workflow_step",
                    aggregate_id=step.id,
                    event_type=STEP_READY_EVENT,
                    dedupe_key=f"workflow-step:{step.id}:ready:v{claimed.step.version}",
                    payload=_step_ready_payload(run, claimed.step),
                )
                continue
            # claim 未成功（并发/终态）→ 落原 execute 分支（execute 侧自行 claim，busy 则 no-op）。
        await enqueue(
            session,
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
