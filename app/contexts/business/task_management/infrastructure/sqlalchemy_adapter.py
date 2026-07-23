"""SQLAlchemy adapters for Task records and Workflow progress projections."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.business.task_management.application.contracts import (
    CreateTaskRequest,
    TaskLogView,
    TaskView,
    TaskVisibility,
)
from app.contexts.business.task_management.contracts.tasks import (
    TASK_DECISION_RECORDED_V1,
    TaskDecisionRecordedV1,
)
from app.contexts.business.task_management.domain import state_machine
from app.contexts.foundations.execution.workflow_runtime.contracts.runtime import (
    WorkflowProgressedV1,
    WorkflowRunStatus,
    WorkflowStepStatus,
)
from app.contexts.shared_kernel import ResourceNotFound, RuleViolation
from app.models.task import TaskCard, TaskCardLog
from app.platform.outbox.repository import enqueue

if TYPE_CHECKING:
    from app.models.system import SysUser

_PROJECTION_VERSIONS = "_workflow_projection_versions"


class SQLAlchemyTaskManagementAdapter:
    """Retain the ORM-shaped compatibility surface behind Task ownership."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _task_view(task: TaskCard) -> TaskView:
        return TaskView(
            id=task.id,
            title=task.title,
            task_type=task.task_type,
            priority=task.priority,
            status=task.status,
            creator_id=task.creator_id,
            assignee_agent_id=task.assignee_agent_id,
            parent_id=task.parent_id,
            sla_hours=task.sla_hours,
            result_content=task.result_content,
            create_time=task.create_time,
            department_id=task.department_id,
            assignee_user_id=task.assignee_user_id,
            assignee_type=task.assignee_type,
            payload=tuple((task.payload or {}).items()),
            step_no=task.step_no,
        )

    @staticmethod
    def _log_view(log: TaskCardLog) -> TaskLogView:
        return TaskLogView(
            id=log.id,
            from_status=log.from_status,
            to_status=log.to_status,
            operator_id=log.operator_id,
            note=log.note,
            create_time=log.create_time,
        )

    async def create_view(self, request: CreateTaskRequest) -> TaskView:
        task = await self.create_record(
            title=request.title,
            task_type=request.task_type,
            creator_id=request.creator_id,
            priority=request.priority,
            assignee_agent_id=request.assignee_agent_id,
            parent_id=request.parent_id,
            sla_hours=request.sla_hours,
            payload=dict(request.payload),
        )
        return self._task_view(task)

    async def get_view(self, task_id: uuid.UUID) -> TaskView:
        return self._task_view(await self.get_record(task_id))

    async def list_views(
        self,
        *,
        status: str | None,
        parent_id: uuid.UUID | None,
        limit: int,
        visibility: TaskVisibility,
    ) -> tuple[TaskView, ...]:
        statement = select(TaskCard).where(TaskCard.is_delete.is_(False))
        if status:
            statement = statement.where(TaskCard.status == status)
        if parent_id:
            statement = statement.where(TaskCard.parent_id == parent_id)
        if not visibility.unrestricted:
            conditions = [TaskCard.creator_id == visibility.principal_id]
            if visibility.department_id is not None:
                conditions.append(TaskCard.department_id == visibility.department_id)
            conditions.append(TaskCard.assignee_user_id == visibility.principal_id)
            statement = statement.where(or_(*conditions))
        rows = (
            await self._session.execute(
                statement.order_by(TaskCard.create_time.desc()).limit(limit)
            )
        ).scalars()
        return tuple(self._task_view(row) for row in rows)

    async def list_log_views(self, task_id: uuid.UUID) -> tuple[TaskLogView, ...]:
        return tuple(self._log_view(log) for log in await self.list_logs(task_id))

    async def transition_view(
        self,
        task_id: uuid.UUID,
        to_status: str,
        *,
        operator_id: uuid.UUID | None,
        note: str | None = None,
        result_content: str | None = None,
    ) -> TaskView:
        task = await self.transition_record(
            task_id,
            to_status,
            operator_id=operator_id,
            note=note,
            result_content=result_content,
        )
        return self._task_view(task)

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
    ) -> TaskCard:
        task = TaskCard(
            id=task_id or uuid.uuid4(),
            title=title,
            task_type=task_type,
            creator_id=creator_id,
            priority=priority,
            assignee_agent_id=assignee_agent_id,
            parent_id=parent_id,
            sla_hours=sla_hours,
            payload=payload or {},
            step_no=step_no,
        )
        self._session.add(task)
        await self._session.flush()
        await self._log(task.id, None, state_machine.CREATED, creator_id, "创建任务")
        await self._session.flush()
        await self._session.refresh(task)
        return task

    async def get_record(self, task_id: uuid.UUID) -> TaskCard:
        task = await self._session.get(TaskCard, task_id)
        if task is None or task.is_delete:
            raise ResourceNotFound("任务不存在")
        return task

    async def transition_record(
        self,
        task_id: uuid.UUID,
        to_status: str,
        *,
        operator_id: uuid.UUID | None,
        note: str | None = None,
        result_content: str | None = None,
        publish_decision: bool = True,
    ) -> TaskCard:
        task = await self.get_record(task_id)
        state_machine.assert_transition(task.status, to_status)
        from_status = task.status
        task.status = to_status
        if result_content is not None:
            task.result_content = result_content
        await self._log(task.id, from_status, to_status, operator_id, note)
        if publish_decision and to_status in {
            state_machine.ACCEPTED,
            state_machine.REJECTED,
        }:
            await self._publish_decision(task, to_status, operator_id)
        await self._session.flush()
        await self._session.refresh(task)
        return task

    async def decompose_records(
        self,
        parent_id: uuid.UUID,
        subtasks: list[dict[str, Any]],
        *,
        creator_id: uuid.UUID,
    ) -> list[TaskCard]:
        if not subtasks:
            raise RuleViolation("子任务列表为空")
        parent = await self.get_record(parent_id)
        children: list[TaskCard] = []
        for subtask in subtasks:
            title = subtask.get("title")
            if not title:
                raise RuleViolation("子任务缺少 title")
            child = await self.create_record(
                title=str(title),
                task_type=str(subtask.get("task_type", parent.task_type)),
                creator_id=creator_id,
                priority=str(subtask.get("priority", parent.priority)),
                assignee_agent_id=subtask.get("assignee_agent_id"),
                parent_id=parent.id,
                payload=subtask.get("payload", {}),
            )
            children.append(child)
        return children

    async def list_records(
        self,
        *,
        status: str | None = None,
        parent_id: uuid.UUID | None = None,
        limit: int = 100,
        viewer: SysUser | None = None,
        visibility_filter: Any = None,
    ) -> list[TaskCard]:
        statement = select(TaskCard).where(TaskCard.is_delete.is_(False))
        if status:
            statement = statement.where(TaskCard.status == status)
        if parent_id:
            statement = statement.where(TaskCard.parent_id == parent_id)
        if viewer is not None and visibility_filter is not None:
            condition = visibility_filter(TaskCard, viewer)
            if condition is not None:
                statement = statement.where(condition)
        statement = statement.order_by(TaskCard.create_time.desc()).limit(limit)
        return list((await self._session.execute(statement)).scalars())

    async def list_logs(self, task_id: uuid.UUID) -> list[TaskCardLog]:
        statement = (
            select(TaskCardLog)
            .where(TaskCardLog.task_id == task_id)
            .order_by(TaskCardLog.create_time)
        )
        return list((await self._session.execute(statement)).scalars())

    async def apply_workflow_progress(self, event: WorkflowProgressedV1) -> bool:
        task_id = event.task_card_id or event.parent_task_id
        task = await self._session.get(TaskCard, task_id)
        stream = f"step:{event.step_id}" if event.step_id else "run"
        incoming_version = event.step_version if event.step_id else event.run_version
        if incoming_version is None:
            incoming_version = 0
        if task is not None and self._projection_version(task, stream) >= incoming_version:
            return False
        if task is None:
            task = await self._create_projection_record(event, task_id)
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
                await self.transition_record(
                    task.id,
                    state_machine.REPORTED,
                    operator_id=event.expert_id,
                    note=(
                        "workflow step 完成"
                        if event.step_status != WorkflowStepStatus.FAILED
                        else "workflow step 失败"
                    ),
                    result_content=event.result_content,
                    publish_decision=False,
                )
            if (
                event.step_status == WorkflowStepStatus.SUCCEEDED
                and not event.red_line
                and task.status == state_machine.REPORTED
            ):
                await self.transition_record(
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
                    "red_line": event.red_line,
                }
            )
            task.payload = payload
        await self._session.flush()
        return True

    async def apply(self, event: WorkflowProgressedV1) -> bool:
        return await self.apply_workflow_progress(event)

    async def _create_projection_record(
        self, event: WorkflowProgressedV1, task_id: uuid.UUID
    ) -> TaskCard:
        is_step = event.step_id is not None
        task = await self.create_record(
            task_id=task_id,
            title=(event.step_title if is_step else event.title) or event.title,
            task_type=(event.capability_key if is_step else "orchestration") or "other",
            creator_id=event.creator_id,
            assignee_agent_id=event.expert_id,
            parent_id=event.parent_task_id if is_step else None,
            step_no=event.step_number if is_step else None,
            payload={
                "origin": "workflow",
                "request": event.request_text,
                "instruction": event.instruction,
                "skill": event.capability_key,
                "red_line": event.red_line,
                "workflow_run_id": str(event.workflow_id),
                "workflow_step_id": str(event.step_id) if event.step_id else None,
                "workflow_step_version": event.step_version,
            },
        )
        task.depends_on = [str(item) for item in event.depends_on_task_ids]
        return task

    async def _apply_parent_status(self, task: TaskCard, event: WorkflowProgressedV1) -> None:
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
            await self.transition_record(
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
            await self.transition_record(
                task.id,
                state_machine.ACCEPTED,
                operator_id=None,
                note="工作流聚合完成",
                publish_decision=False,
            )
        if event.run_status == WorkflowRunStatus.CANCELLED and state_machine.can_transition(
            task.status, state_machine.CANCELLED
        ):
            await self.transition_record(
                task.id,
                state_machine.CANCELLED,
                operator_id=None,
                note="工作流已取消",
                publish_decision=False,
            )

    async def _drive(self, task: TaskCard, targets: tuple[str, ...], *, note: str) -> None:
        for target in targets:
            if state_machine.can_transition(task.status, target):
                await self.transition_record(
                    task.id,
                    target,
                    operator_id=None,
                    note=note,
                    publish_decision=False,
                )

    async def _publish_decision(
        self,
        task: TaskCard,
        decision: str,
        principal_id: uuid.UUID | None,
    ) -> None:
        payload = task.payload or {}
        raw_workflow_id = payload.get("workflow_run_id")
        raw_step_id = payload.get("workflow_step_id")
        raw_version = payload.get("workflow_step_version")
        if (
            principal_id is None
            or raw_workflow_id is None
            or raw_step_id is None
            or not isinstance(raw_version, int)
        ):
            return
        event = TaskDecisionRecordedV1(
            event_id=uuid.uuid4(),
            task_id=task.id,
            workflow_id=uuid.UUID(str(raw_workflow_id)),
            workflow_step_id=uuid.UUID(str(raw_step_id)),
            expected_step_version=raw_version,
            decision=decision,
            principal_id=principal_id,
            occurred_at=datetime.now(UTC),
        )
        await enqueue(
            self._session,
            event_id=event.event_id,
            aggregate_type="task",
            aggregate_id=task.id,
            event_type=TASK_DECISION_RECORDED_V1,
            dedupe_key=(f"task-decision:{task.id}:{decision}:step-v{event.expected_step_version}"),
            payload=task_decision_to_payload(event),
        )

    async def _log(
        self,
        task_id: uuid.UUID,
        from_status: str | None,
        to_status: str,
        operator_id: uuid.UUID | None,
        note: str | None,
    ) -> None:
        self._session.add(
            TaskCardLog(
                task_id=task_id,
                from_status=from_status,
                to_status=to_status,
                operator_id=operator_id,
                note=note,
            )
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


def task_decision_to_payload(event: TaskDecisionRecordedV1) -> dict[str, object]:
    return {
        "event_id": str(event.event_id),
        "task_id": str(event.task_id),
        "workflow_id": str(event.workflow_id),
        "workflow_step_id": str(event.workflow_step_id),
        "expected_step_version": event.expected_step_version,
        "decision": event.decision,
        "principal_id": str(event.principal_id),
        "occurred_at": event.occurred_at.isoformat(),
        "contract_version": event.contract_version,
    }


def task_decision_from_payload(payload: dict[str, Any]) -> TaskDecisionRecordedV1:
    return TaskDecisionRecordedV1(
        event_id=uuid.UUID(str(payload["event_id"])),
        task_id=uuid.UUID(str(payload["task_id"])),
        workflow_id=uuid.UUID(str(payload["workflow_id"])),
        workflow_step_id=uuid.UUID(str(payload["workflow_step_id"])),
        expected_step_version=int(payload["expected_step_version"]),
        decision=str(payload["decision"]),
        principal_id=uuid.UUID(str(payload["principal_id"])),
        occurred_at=datetime.fromisoformat(str(payload["occurred_at"])),
        contract_version=int(payload.get("contract_version", 1)),
    )


class SQLAlchemyTaskTransaction:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()
