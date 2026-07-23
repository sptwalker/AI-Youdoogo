"""Published platform adapters used by Task Management."""

import json
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.business.task_management.application.contracts import (
    TaskExecutionRequest,
    TaskExecutionResult,
    TaskView,
)
from app.contexts.business.task_management.infrastructure import legacy_workflow
from app.contexts.business.task_management.infrastructure.sqlalchemy_adapter import (
    SQLAlchemyTaskManagementAdapter,
)
from app.contexts.foundations.execution.agent_execution.public import (
    AgentExecutionRequest,
    execute_agent,
)
from app.contexts.foundations.execution.workflow_runtime.public import (
    progress_for_task,
    resume_task_step,
)
from app.contexts.foundations.governance.audit_trail.public import (
    AppendAuditRecordCommand,
    append_audit_record,
)
from app.contexts.foundations.workforce.expert_management.public import (
    get_expert_execution,
)
from app.contexts.shared_kernel import RuleViolation


class PublishedTaskAuditAdapter:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record_decision(
        self,
        *,
        task: TaskView,
        actor_id: uuid.UUID,
        actor_role: str,
        decision: str,
    ) -> None:
        await append_audit_record(
            self._session,
            AppendAuditRecordCommand(
                actor_id=actor_id,
                actor_role=actor_role,
                action=f"task.{decision}",
                summary=f"任务验收 {task.title[:40]} → {decision}",
                target_type="task_card",
                target_id=task.id,
            ),
        )


class PublishedTaskExecutionAdapter:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def execute(self, request: TaskExecutionRequest) -> TaskExecutionResult:
        expert = await get_expert_execution(self._session, request.assignee_agent_id)
        if expert is None:
            raise RuleViolation("指派的智能体角色不存在或已停用")
        result = await execute_agent(
            self._session,
            AgentExecutionRequest(
                expert=expert,
                task_type=request.task_type,
                input_summary=f"任务卡执行：{request.title[:40]}",
                user_message=self._message(request),
                user_id=request.operator_id,
                use_knowledge=True,
            ),
        )
        content = result.content or (result.error.message if result.error else None) or "（无产出）"
        return TaskExecutionResult(
            executor_id=expert.expert_id,
            execution_status=result.status.value,
            content=content,
        )

    @staticmethod
    def _message(request: TaskExecutionRequest) -> str:
        parts = [f"任务标题：{request.title}", f"任务类型：{request.task_type}"]
        payload = dict(request.payload)
        if payload:
            parts.append("任务输入：\n" + json.dumps(payload, ensure_ascii=False, indent=2))
        parts.append("请完成该任务并给出结构化结果。")
        return "\n".join(parts)


class PublishedTaskWorkflowAdapter:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._projection = SQLAlchemyTaskManagementAdapter(session)

    async def resume_if_step(
        self, task: TaskView, *, operator_id: uuid.UUID
    ) -> dict[str, object] | None:
        durable = await resume_task_step(
            self._session,
            task_card_id=task.id,
            parent_task_id=task.parent_id,
            step_number=task.step_no,
            operator_id=operator_id,
            task_projection=self._projection,
        )
        if durable is not None:
            return durable
        if task.step_no is None or task.parent_id is None:
            return None
        return await legacy_workflow.advance(
            self._session,
            task.parent_id,
            operator_id=operator_id,
        )

    async def progress(self, parent_task_id: uuid.UUID) -> dict[str, object]:
        durable = await progress_for_task(self._session, parent_task_id)
        if durable is not None:
            return durable
        return await legacy_workflow.progress(self._session, parent_task_id)
