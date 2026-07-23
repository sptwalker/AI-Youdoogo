"""Workflow progress event serialization and transactional publication."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.execution.workflow_runtime.application.ports import (
    TaskProjectionPort,
)
from app.contexts.foundations.execution.workflow_runtime.contracts.runtime import (
    WORKFLOW_PROGRESSED_V1,
    WorkflowProgressedV1,
    WorkflowRunStatus,
    WorkflowStepStatus,
)
from app.platform.outbox.model import OUTBOX_DONE
from app.platform.outbox.repository import enqueue


async def publish_workflow_progress(
    session: AsyncSession,
    projection: TaskProjectionPort,
    event: WorkflowProgressedV1,
) -> None:
    """Apply the compatibility projection and append the replayable event atomically."""
    await projection.apply(event)
    outbox_event = await enqueue(
        session,
        event_id=event.event_id,
        aggregate_type="workflow",
        aggregate_id=event.workflow_id,
        event_type=WORKFLOW_PROGRESSED_V1,
        dedupe_key=f"workflow-progress:{event.event_id}",
        payload=workflow_progress_to_payload(event),
    )
    # The compatibility projection above is the current in-process delivery adapter.
    # Mark its durable envelope delivered; it remains available for audit/manual replay.
    outbox_event.status = OUTBOX_DONE


def workflow_progress_to_payload(event: WorkflowProgressedV1) -> dict[str, object]:
    return {
        "event_id": str(event.event_id),
        "workflow_id": str(event.workflow_id),
        "run_version": event.run_version,
        "occurred_at": event.occurred_at.isoformat(),
        "transition": event.transition,
        "parent_task_id": str(event.parent_task_id),
        "creator_id": str(event.creator_id),
        "title": event.title,
        "request_text": event.request_text,
        "run_status": event.run_status.value,
        "step_status": event.step_status.value if event.step_status else None,
        "step_id": str(event.step_id) if event.step_id else None,
        "task_card_id": str(event.task_card_id) if event.task_card_id else None,
        "step_version": event.step_version,
        "step_number": event.step_number,
        "step_title": event.step_title,
        "capability_key": event.capability_key,
        "instruction": event.instruction,
        "red_line": event.red_line,
        "expert_id": str(event.expert_id) if event.expert_id else None,
        "depends_on_task_ids": [str(item) for item in event.depends_on_task_ids],
        "result_content": event.result_content,
        "error": event.error,
    }


def workflow_progress_from_payload(payload: dict[str, Any]) -> WorkflowProgressedV1:
    raw_step_status = payload.get("step_status")
    return WorkflowProgressedV1(
        event_id=uuid.UUID(str(payload["event_id"])),
        workflow_id=uuid.UUID(str(payload["workflow_id"])),
        run_version=int(payload["run_version"]),
        occurred_at=datetime.fromisoformat(str(payload["occurred_at"])),
        transition=str(payload["transition"]),
        parent_task_id=uuid.UUID(str(payload["parent_task_id"])),
        creator_id=uuid.UUID(str(payload["creator_id"])),
        title=str(payload["title"]),
        request_text=str(payload["request_text"]),
        run_status=WorkflowRunStatus(str(payload["run_status"])),
        step_status=(
            WorkflowStepStatus(str(raw_step_status)) if raw_step_status is not None else None
        ),
        step_id=_optional_uuid(payload.get("step_id")),
        task_card_id=_optional_uuid(payload.get("task_card_id")),
        step_version=_optional_int(payload.get("step_version")),
        step_number=_optional_int(payload.get("step_number")),
        step_title=_optional_str(payload.get("step_title")),
        capability_key=_optional_str(payload.get("capability_key")),
        instruction=_optional_str(payload.get("instruction")),
        red_line=bool(payload.get("red_line", False)),
        expert_id=_optional_uuid(payload.get("expert_id")),
        depends_on_task_ids=tuple(
            uuid.UUID(str(item)) for item in payload.get("depends_on_task_ids", [])
        ),
        result_content=_optional_str(payload.get("result_content")),
        error=_optional_str(payload.get("error")),
    )


def _optional_uuid(value: object) -> uuid.UUID | None:
    return uuid.UUID(str(value)) if value is not None else None


def _optional_int(value: object) -> int | None:
    return int(value) if value is not None else None  # type: ignore[call-overload]


def _optional_str(value: object) -> str | None:
    return str(value) if value is not None else None
