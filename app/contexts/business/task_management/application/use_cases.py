"""Task card CRUD, lifecycle, execution, and workflow coordination."""

from __future__ import annotations

import uuid
from typing import Any

from app.contexts.business.task_management.application.contracts import (
    CreateTaskRequest,
    DecomposeTaskRequest,
    EditTaskRequest,
    RunTaskRequest,
    TaskDetailView,
    TaskExecutionRequest,
    TaskPrincipal,
    TaskView,
    TaskVisibility,
    TransitionTaskRequest,
)
from app.contexts.business.task_management.application.ports import (
    TaskAuditPort,
    TaskCardRepositoryPort,
    TaskExecutionPort,
    TaskTransactionPort,
    TaskWorkflowPort,
)
from app.contexts.business.task_management.domain import state_machine
from app.contexts.shared_kernel import ResourceNotFound, RuleViolation


class TaskManagementApplication:
    def __init__(
        self,
        *,
        tasks: TaskCardRepositoryPort,
        transaction: TaskTransactionPort,
        audit: TaskAuditPort,
        workflow: TaskWorkflowPort | None = None,
        executor: TaskExecutionPort | None = None,
    ) -> None:
        self._tasks = tasks
        self._transaction = transaction
        self._audit = audit
        self._workflow = workflow
        self._executor = executor

    async def create(self, request: CreateTaskRequest) -> TaskView:
        task = await self.stage(request)
        await self._transaction.commit()
        return await self._tasks.get_view(task.id)

    async def stage(self, request: CreateTaskRequest) -> TaskView:
        """Create within an existing caller-owned transaction without committing it."""
        return await self._tasks.create_view(request)

    async def edit(self, request: EditTaskRequest) -> TaskView:
        # 补指派/改标题优先级；仅未开跑状态可编辑，状态守卫在 repo（domain assert_editable）。
        await self._tasks.edit_view(request)
        await self._transaction.commit()
        return await self._tasks.get_view(request.task_id)

    async def list(
        self,
        principal: TaskPrincipal,
        *,
        status: str | None,
        limit: int,
    ) -> tuple[TaskView, ...]:
        return await self._tasks.list_views(
            status=status,
            parent_id=None,
            limit=limit,
            visibility=self._visibility(principal),
        )

    async def detail(self, principal: TaskPrincipal, task_id: uuid.UUID) -> TaskDetailView:
        task = await self._tasks.get_view(task_id)
        self._ensure_visible(principal, task)
        return TaskDetailView(
            task=task,
            logs=await self._tasks.list_log_views(task_id),
        )

    async def decompose(self, request: DecomposeTaskRequest) -> tuple[TaskView, ...]:
        if not request.subtasks:
            raise RuleViolation("子任务列表为空")
        parent = await self._tasks.get_view(request.parent_id)
        children: list[TaskView] = []
        for subtask in request.subtasks:
            children.append(
                await self._tasks.create_view(
                    CreateTaskRequest(
                        title=subtask.title,
                        task_type=subtask.task_type or parent.task_type,
                        creator_id=request.creator_id,
                        priority=subtask.priority or parent.priority,
                        assignee_agent_id=subtask.assignee_agent_id,
                        parent_id=parent.id,
                        payload=subtask.payload,
                    )
                )
            )
        await self._transaction.commit()
        persisted: list[TaskView] = []
        for child in children:
            persisted.append(await self._tasks.get_view(child.id))
        return tuple(persisted)

    async def transition(self, request: TransitionTaskRequest) -> TaskView:
        task = await self._tasks.transition_view(
            request.task_id,
            request.to_status,
            operator_id=request.operator_id,
            note=request.note,
            result_content=request.result_content,
        )
        resumed = None
        if request.to_status == state_machine.ACCEPTED and self._workflow is not None:
            resumed = await self._workflow.resume_if_step(
                task,
                operator_id=request.operator_id,
            )
        if resumed is None:
            await self._transaction.commit()
        task = await self._tasks.get_view(task.id)
        if request.to_status in {state_machine.ACCEPTED, state_machine.REJECTED}:
            await self._audit.record_decision(
                task=task,
                actor_id=request.operator_id,
                actor_role=request.operator_role,
                decision=request.to_status,
            )
        return task

    async def progress(self, parent_task_id: uuid.UUID) -> dict[str, Any]:
        if self._workflow is None:
            raise RuntimeError("Task workflow adapter is not configured")
        return await self._workflow.progress(parent_task_id)

    async def run(self, request: RunTaskRequest) -> TaskView:
        if self._executor is None:
            raise RuntimeError("Task execution adapter is not configured")
        task = await self._tasks.get_view(request.task_id)
        if task.assignee_type == "user":
            raise RuleViolation("该任务派给真人受理，不由调度中枢自动执行")
        if task.assignee_agent_id is None:
            raise RuleViolation("任务未分配智能体，无法自动执行")
        assignee_agent_id = task.assignee_agent_id

        if task.status == state_machine.CREATED:
            task = await self._tasks.transition_view(
                task.id,
                state_machine.DISPATCHED,
                operator_id=request.operator_id,
                note="调度中枢分发",
            )
            await self._transaction.commit()
        if task.status != state_machine.DISPATCHED:
            raise RuleViolation(f"任务当前状态 {task.status} 不可执行（需为 created/dispatched）")

        await self._tasks.transition_view(
            task.id,
            state_machine.EXECUTING,
            operator_id=request.operator_id,
            note="调度中枢开始执行",
        )
        await self._transaction.commit()
        execution = await self._executor.execute(
            TaskExecutionRequest(
                task_id=task.id,
                title=task.title,
                task_type=task.task_type,
                payload=task.payload,
                assignee_agent_id=assignee_agent_id,
                operator_id=request.operator_id,
            )
        )
        task = await self._tasks.transition_view(
            task.id,
            state_machine.REPORTED,
            operator_id=execution.executor_id,
            note=f"智能体执行 status={execution.execution_status}",
            result_content=execution.content,
        )
        await self._transaction.commit()
        return await self._tasks.get_view(task.id)

    @staticmethod
    def _visibility(principal: TaskPrincipal) -> TaskVisibility:
        if principal.sees_all_rows:
            return TaskVisibility(unrestricted=True)
        return TaskVisibility(
            unrestricted=False,
            principal_id=principal.id,
            department_id=principal.department_id,
        )

    @staticmethod
    def _ensure_visible(principal: TaskPrincipal, task: TaskView) -> None:
        if principal.sees_all_rows:
            return
        if task.creator_id == principal.id or task.assignee_user_id == principal.id:
            return
        if task.department_id is not None and task.department_id == principal.department_id:
            return
        raise ResourceNotFound("资源不存在")
