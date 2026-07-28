"""Projection of durable workflow progress into Task Management records."""

from __future__ import annotations

import uuid
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.business.task_management.domain import state_machine
from app.contexts.business.task_management.infrastructure.workflow_event_acl import (
    WorkflowProjectionData,
    decode_workflow_progress,
)
from app.contexts.foundations.execution.workflow_runtime.contracts.runtime import (
    WorkflowProgressedV1,
    WorkflowRunStatus,
    WorkflowStepStatus,
)
from app.models.task import TaskCard

_PROJECTION_VERSIONS = "_workflow_projection_versions"


class TaskProjectionRecordStore(Protocol):
    async def create_record(
        self,
        *,
        title: str,
        task_type: str,
        creator_id: uuid.UUID,
        priority: str = "normal",
        assignee_agent_id: uuid.UUID | None = None,
        parent_id: uuid.UUID | None = None,
        sla_hours: int | None = None,
        payload: dict[str, Any] | None = None,
        step_no: int | None = None,
        task_id: uuid.UUID | None = None,
    ) -> TaskCard: ...

    async def transition_record(
        self,
        task_id: uuid.UUID,
        to_status: str,
        *,
        operator_id: uuid.UUID | None,
        note: str | None = None,
        result_content: str | None = None,
        publish_decision: bool = True,
    ) -> TaskCard: ...


class SQLAlchemyWorkflowTaskProjection:
    """Own the idempotent workflow-to-task projection state machine."""

    def __init__(
        self,
        session: AsyncSession,
        records: TaskProjectionRecordStore,
    ) -> None:
        self._session = session
        self._records = records

    async def apply(self, event: WorkflowProgressedV1) -> bool:
        data = decode_workflow_progress(event)
        task_id = data.task_card_id or data.parent_task_id
        task = await self._session.get(TaskCard, task_id)
        stream = f"step:{event.step_id}" if event.step_id else "run"
        incoming_version = event.step_version if event.step_id else event.run_version
        if incoming_version is None:
            incoming_version = 0
        if task is not None and self._projection_version(task, stream) >= incoming_version:
            return False
        if task is None:
            task = await self._create_projection_record(event, data, task_id)
        if event.transition == "step.claimed":
            await self._drive(
                task,
                (state_machine.DISPATCHED, state_machine.EXECUTING),
                note="workflow worker 执行",
            )
        elif event.transition in {"step.completed", "step.waiting_human"}:
            await self._drive(
                task,
                (state_machine.DISPATCHED, state_machine.EXECUTING),
                note="workflow worker 执行",
            )
            if task.status == state_machine.EXECUTING:
                await self._records.transition_record(
                    task.id,
                    state_machine.REPORTED,
                    operator_id=data.expert_id,
                    note=(
                        "workflow step 完成"
                        if event.step_status != WorkflowStepStatus.FAILED
                        else "workflow step 失败"
                    ),
                    result_content=data.result_content,
                    publish_decision=False,
                )
            if (
                event.step_status == WorkflowStepStatus.SUCCEEDED
                and not data.red_line
                and task.status == state_machine.REPORTED
            ):
                await self._records.transition_record(
                    task.id,
                    state_machine.ACCEPTED,
                    operator_id=None,
                    note="非红线步骤自动验收",
                    publish_decision=False,
                )
        elif event.step_id is None:
            await self._apply_parent_status(task, event)
        self._record_projection_version(task, stream, incoming_version)
        if event.step_id is not None:
            payload = dict(task.payload or {})
            payload.update(
                {
                    "workflow_run_id": str(event.workflow_id),
                    "workflow_step_id": str(event.step_id),
                    "workflow_step_version": event.step_version,
                    "red_line": data.red_line,
                }
            )
            task.payload = payload
        await self._session.flush()
        return True

    async def _create_projection_record(
        self,
        event: WorkflowProgressedV1,
        data: WorkflowProjectionData,
        task_id: uuid.UUID,
    ) -> TaskCard:
        is_step = event.step_id is not None
        task = await self._records.create_record(
            task_id=task_id,
            title=(data.step_title if is_step else data.title) or data.title,
            task_type=(data.capability_key if is_step else "orchestration") or "other",
            creator_id=data.creator_id,
            assignee_agent_id=data.expert_id,
            parent_id=data.parent_task_id if is_step else None,
            step_no=event.step_number if is_step else None,
            payload={
                "origin": "workflow",
                "request": data.request_text,
                "instruction": data.instruction,
                "skill": data.capability_key,
                "red_line": data.red_line,
                "workflow_run_id": str(event.workflow_id),
                "workflow_step_id": str(event.step_id) if event.step_id else None,
                "workflow_step_version": event.step_version,
            },
        )
        task.depends_on = [str(item) for item in data.depends_on_task_ids]
        return task

    async def _apply_parent_status(
        self, task: TaskCard, event: WorkflowProgressedV1
    ) -> None:
        if event.run_status in {
            WorkflowRunStatus.RUNNING,
            WorkflowRunStatus.WAITING_HUMAN,
            WorkflowRunStatus.SUCCEEDED,
            WorkflowRunStatus.FAILED,
            WorkflowRunStatus.CANCELLED,
        }:
            await self._drive(
                task,
                (state_machine.DISPATCHED, state_machine.EXECUTING),
                note="工作流执行中",
            )
        if (
            event.run_status in {WorkflowRunStatus.SUCCEEDED, WorkflowRunStatus.FAILED}
            and task.status == state_machine.EXECUTING
        ):
            await self._records.transition_record(
                task.id,
                state_machine.REPORTED,
                operator_id=None,
                note=(
                    "工作流完成"
                    if event.run_status == WorkflowRunStatus.SUCCEEDED
                    else "工作流失败"
                ),
                result_content=(
                    "工作流已完成"
                    if event.run_status == WorkflowRunStatus.SUCCEEDED
                    else event.error
                ),
                publish_decision=False,
            )
        if (
            event.run_status == WorkflowRunStatus.SUCCEEDED
            and task.status == state_machine.REPORTED
        ):
            await self._records.transition_record(
                task.id,
                state_machine.ACCEPTED,
                operator_id=None,
                note="工作流聚合完成",
                publish_decision=False,
            )
        if event.run_status == WorkflowRunStatus.CANCELLED and state_machine.can_transition(
            task.status, state_machine.CANCELLED
        ):
            await self._records.transition_record(
                task.id,
                state_machine.CANCELLED,
                operator_id=None,
                note="工作流已取消",
                publish_decision=False,
            )

    async def _drive(self, task: TaskCard, targets: tuple[str, ...], *, note: str) -> None:
        for target in targets:
            if state_machine.can_transition(task.status, target):
                await self._records.transition_record(
                    task.id,
                    target,
                    operator_id=None,
                    note=note,
                    publish_decision=False,
                )

    @staticmethod
    def _projection_version(task: TaskCard, stream: str) -> int:
        versions = (task.payload or {}).get(_PROJECTION_VERSIONS, {})
        if not isinstance(versions, dict):
            return -1
        value = versions.get(stream, -1)
        return value if isinstance(value, int) else -1

    @staticmethod
    def _record_projection_version(task: TaskCard, stream: str, version: int) -> None:
        payload = dict(task.payload or {})
        versions = dict(payload.get(_PROJECTION_VERSIONS, {}))
        versions[stream] = version
        payload[_PROJECTION_VERSIONS] = versions
        task.payload = payload
