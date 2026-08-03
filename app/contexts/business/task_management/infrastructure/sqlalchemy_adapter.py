"""Compatibility facade for Task Management SQLAlchemy infrastructure."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.business.task_management.application.contracts import (
    CreateTaskRequest,
    EditTaskRequest,
    TaskLogView,
    TaskView,
    TaskVisibility,
)
from app.contexts.business.task_management.domain import state_machine
from app.contexts.foundations.execution.workflow_runtime.contracts.runtime import (
    WorkflowProgressedV1,
)
from app.contexts.shared_kernel import ResourceNotFound, RuleViolation
from app.models.task import TaskCard, TaskCardLog

from .task_decisions import (
    SQLAlchemyTaskDecisionPublisher,
    task_decision_from_payload,
    task_decision_to_payload,
)
from .workflow_projection import SQLAlchemyWorkflowTaskProjection

if TYPE_CHECKING:
    from app.models.system import SysUser

__all__ = [
    "SQLAlchemyTaskManagementAdapter",
    "task_decision_from_payload",
    "task_decision_to_payload",
]


class SQLAlchemyTaskManagementAdapter:
    """Retain the ORM-shaped compatibility surface behind Task ownership."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._decision_publisher = SQLAlchemyTaskDecisionPublisher(session)
        self._workflow_projection = SQLAlchemyWorkflowTaskProjection(session, self)

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

    async def edit_view(self, request: EditTaskRequest) -> TaskView:
        task = await self.get_record(request.task_id)
        state_machine.assert_editable(task.status)
        if request.title is not None:
            task.title = request.title
        if request.priority is not None:
            task.priority = request.priority
        if request.assignee_agent_id is not None:
            task.assignee_agent_id = request.assignee_agent_id
        await self._session.flush()
        await self._session.refresh(task)
        return self._task_view(task)

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
        return await self._workflow_projection.apply(event)

    async def apply(self, event: WorkflowProgressedV1) -> bool:
        return await self.apply_workflow_progress(event)

    async def _publish_decision(
        self,
        task: TaskCard,
        decision: str,
        principal_id: uuid.UUID | None,
    ) -> None:
        await self._decision_publisher.publish_transition(task, decision, principal_id)

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
