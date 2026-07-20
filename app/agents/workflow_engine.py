"""工作流推进端口与当前数据库实现。

LangGraph 后续只能实现此端口或其 planner 子端口；可靠状态、Outbox、ToolExecution 与
真人停点仍由持久化 runtime 负责，不能由图框架旁路。
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import TaskCard
from app.models.workflow import WorkflowRun
from app.services import workflow_service
from app.services.workflow_service import PlanStepLike


class WorkflowEngine(Protocol):
    """规划器/图框架可替换的稳定工作流适配边界。"""

    async def submit(
        self,
        db: AsyncSession,
        *,
        request: str,
        title: str,
        creator_id: uuid.UUID,
        assignee_agent_id: uuid.UUID | None,
        steps: Sequence[PlanStepLike],
        is_red_line: Callable[[str], bool],
    ) -> WorkflowRun: ...

    async def progress(self, db: AsyncSession, parent_task_id: uuid.UUID) -> dict[str, Any]: ...

    async def accept_human_step(
        self,
        db: AsyncSession,
        task: TaskCard,
        *,
        operator_id: uuid.UUID | None,
    ) -> WorkflowRun | None: ...


class DatabaseWorkflowEngine:
    """当前自研 DAG runtime；所有变更只 flush，由 use case 管理提交。"""

    async def submit(
        self,
        db: AsyncSession,
        *,
        request: str,
        title: str,
        creator_id: uuid.UUID,
        assignee_agent_id: uuid.UUID | None,
        steps: Sequence[PlanStepLike],
        is_red_line: Callable[[str], bool],
    ) -> WorkflowRun:
        return await workflow_service.create_workflow(
            db,
            request=request,
            title=title,
            creator_id=creator_id,
            assignee_agent_id=assignee_agent_id,
            steps=steps,
            is_red_line=is_red_line,
        )

    async def progress(self, db: AsyncSession, parent_task_id: uuid.UUID) -> dict[str, Any]:
        return await workflow_service.progress(db, parent_task_id)

    async def accept_human_step(
        self,
        db: AsyncSession,
        task: TaskCard,
        *,
        operator_id: uuid.UUID | None,
    ) -> WorkflowRun | None:
        return await workflow_service.accept_human_step(db, task.id, operator_id=operator_id)


_database_engine = DatabaseWorkflowEngine()


def get_workflow_engine() -> WorkflowEngine:
    """返回当前 workflow adapter；未来可在此切换 LangGraph POC。"""
    return _database_engine
