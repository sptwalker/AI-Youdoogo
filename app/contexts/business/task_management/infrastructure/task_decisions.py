"""Task decision event serialization and outbox publication."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.business.task_management.contracts.tasks import (
    TASK_DECISION_RECORDED_V1,
    TaskDecisionRecordedV1,
)
from app.models.task import TaskCard
from app.platform.outbox.repository import enqueue


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


class SQLAlchemyTaskDecisionPublisher:
    """Publish human task decisions without coupling repositories to event encoding."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def publish_transition(
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
            dedupe_key=(
                f"task-decision:{task.id}:{decision}:step-v{event.expected_step_version}"
            ),
            payload=task_decision_to_payload(event),
        )
