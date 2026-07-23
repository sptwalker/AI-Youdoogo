"""Request-scoped Task Management composition."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.business.task_management.application.ports import (
    TaskExecutionPort,
    TaskWorkflowPort,
)
from app.contexts.business.task_management.application.use_cases import (
    TaskManagementApplication,
)
from app.contexts.business.task_management.infrastructure.adapters import (
    PublishedTaskAuditAdapter,
    PublishedTaskExecutionAdapter,
    PublishedTaskWorkflowAdapter,
)
from app.contexts.business.task_management.infrastructure.sqlalchemy_adapter import (
    SQLAlchemyTaskManagementAdapter,
    SQLAlchemyTaskTransaction,
)


def build_task_management_application(
    session: AsyncSession,
    *,
    workflow: TaskWorkflowPort | None = None,
    executor: TaskExecutionPort | None = None,
) -> TaskManagementApplication:
    return TaskManagementApplication(
        tasks=SQLAlchemyTaskManagementAdapter(session),
        transaction=SQLAlchemyTaskTransaction(session),
        audit=PublishedTaskAuditAdapter(session),
        workflow=workflow or PublishedTaskWorkflowAdapter(session),
        executor=executor or PublishedTaskExecutionAdapter(session),
    )
