"""唤醒停车 step：消费 ``expert.execution.completed.v1`` 回执，复用唯一 writer
写回（docs/23 §6.3.5）。

**绝不另造持久化 writer**：定位停车 step（校验 lease_owner=sentinel & version）→ 重建最小
``ClaimedWorkflowStep``/``PreparedWorkflowStep`` + ``ExecuteWorkflowStepResult`` → 调
``SQLAlchemyWorkflowRepository.finalize``（= 现有 ``complete_step`` + ``pipe_outputs`` +
enqueue ``workflow.advance``）。双层幂等：inbox event_id 首层去重 + ``complete_step``
的 version fence。
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.execution.workflow_runtime.application.ports import (
    TaskProjectionPort,
)
from app.contexts.foundations.execution.workflow_runtime.contracts.runtime import (
    ClaimedWorkflowStep,
    ExecuteWorkflowStepResult,
    FinalizeWorkflowStepCommand,
    PreparedWorkflowStep,
)
from app.contexts.foundations.execution.workflow_runtime.infrastructure import (
    sqlalchemy_repository,
)
from app.contexts.foundations.execution.workflow_runtime.infrastructure.sqlalchemy_uow import (
    SQLAlchemyWorkflowUnitOfWorkFactory,
)
from app.models.workflow import WorkflowStep
from app.platform.eventing.remote_step import REMOTE_SENTINEL


async def apply_completed(
    session: AsyncSession,
    payload: dict[str, Any],
    *,
    task_projection: TaskProjectionPort,
) -> bool:
    """把远端回执写回停车 step。

    返回 finalize 是否生效（幂等重投/版本变 → False，不双写不双 advance）。
    """
    step_id = uuid.UUID(str(payload["workflow_step_id"]))
    step_version = int(payload["step_version"])
    step = await session.get(WorkflowStep, step_id)
    # 预检即幂等：step 已 finalize（lease_owner 变/version 变）或非本 sentinel 停车
    # → no-op（version fence 亦会挡）。
    if (
        step is None
        or step.lease_owner != REMOTE_SENTINEL
        or step.version != step_version
        or step.lease_until is None
    ):
        return False
    run = await sqlalchemy_repository.get_run(session, step.workflow_run_id)
    claim = ClaimedWorkflowStep(
        workflow_id=step.workflow_run_id,
        step_id=step.id,
        task_card_id=step.task_card_id,
        expert_id=step.assignee_agent_id,
        worker_id=REMOTE_SENTINEL,
        attempt=step.attempt,
        version=step_version,
        lease_until=step.lease_until,
    )
    prepared = PreparedWorkflowStep(
        claim=claim,
        trace_id=run.trace_id,
        creator_id=run.creator_id,
        request_text=run.request_text,
        title=step.title,
        capability_key=step.skill,
        instruction=step.instruction,
        expert=None,
    )
    execution = ExecuteWorkflowStepResult(
        succeeded=bool(payload.get("succeeded", False)),
        content=str(payload.get("content") or ""),
        error=payload.get("error"),
    )
    uow = SQLAlchemyWorkflowUnitOfWorkFactory(session, task_projection)()
    result = await uow.workflows.finalize(FinalizeWorkflowStepCommand(prepared, execution))
    return result.applied
