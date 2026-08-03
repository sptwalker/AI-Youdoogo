"""Local Runtime v2 adapter backed by the existing durable workflow unit of work."""

from __future__ import annotations

import uuid

from app.contexts.foundations.execution.work_planning.contracts.planning import (
    PlanningContextReference,
    WorkflowPlan,
    WorkflowPlanStep,
    WorkIntent,
)
from app.contexts.foundations.execution.workflow_runtime.application.planning_translation import (
    planning_to_start_command,
)
from app.contexts.foundations.execution.workflow_runtime.application.ports import (
    WorkflowUnitOfWorkFactory,
)
from app.contexts.foundations.execution.workflow_runtime.contracts.runtime_v2 import (
    RuntimeEngine,
    RuntimeInstanceRefV2,
    RuntimeInstanceStatus,
    RuntimeStartResultV2,
    RuntimeStepSubmissionV2,
    RuntimeSubmissionV2,
)


class LocalRuntimeAdapter:
    """Translate Runtime v2 back to the unchanged local durable runtime contract."""

    def __init__(self, units: WorkflowUnitOfWorkFactory) -> None:
        self._units = units

    async def submit(self, submission: RuntimeSubmissionV2) -> RuntimeStartResultV2:
        command = planning_to_start_command(_to_legacy_plan(submission))
        unit = self._units()
        async with unit:
            try:
                started = await unit.workflows.start(command)
                await unit.commit()
            except Exception:
                await unit.rollback()
                raise
        return RuntimeStartResultV2(
            instance=RuntimeInstanceRefV2(
                runtime_id=str(started.workflow_id),
                business_key=submission.business_key,
                workflow_type=submission.workflow_type,
                engine=RuntimeEngine.LOCAL,
            ),
            status=RuntimeInstanceStatus(started.status.value),
            output_data=(
                ("parent_task_id", str(started.parent_task_id)),
                ("trace_id", str(started.trace_id)),
                ("version", started.version),
            ),
        )


def _to_legacy_plan(submission: RuntimeSubmissionV2) -> WorkflowPlan:
    input_data = dict(submission.input_data)
    references = _context_references(input_data.get("context_references", ()))
    intent = WorkIntent(
        request=_required_string(input_data, "request"),
        title=_optional_string(input_data, "title"),
        creator_id=uuid.UUID(_required_string(input_data, "creator_id")),
        assignee_expert_id=_optional_uuid(input_data, "assignee_expert_id"),
        context_references=references,
    )
    by_business_key = {step.business_key: _step_number(step) for step in submission.steps}
    steps = tuple(
        WorkflowPlanStep(
            number=_step_number(step),
            title=_required_step_string(step, "title"),
            capability_key=_capability_key(step),
            instruction=_required_step_string(step, "instruction"),
            depends_on=tuple(by_business_key[key] for key in step.depends_on),
        )
        for step in sorted(submission.steps, key=_step_number)
    )
    return WorkflowPlan(intent=intent, steps=steps)


def _capability_key(step: RuntimeStepSubmissionV2) -> str:
    if step.executor_ref.namespace != "capability":
        raise ValueError("local runtime only supports capability executor references")
    return step.executor_ref.key


def _step_number(step: RuntimeStepSubmissionV2) -> int:
    value = dict(step.input_data).get("step_number")
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError("local runtime step_number must be a non-negative integer")
    return value


def _required_step_string(step: RuntimeStepSubmissionV2, key: str) -> str:
    value = dict(step.input_data).get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"local runtime step {key} must not be blank")
    return value


def _required_string(values: dict[str, object], key: str) -> str:
    value = values.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"local runtime {key} must not be blank")
    return value


def _optional_string(values: dict[str, object], key: str) -> str | None:
    value = values.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"local runtime {key} must be a string or null")
    return value


def _optional_uuid(values: dict[str, object], key: str) -> uuid.UUID | None:
    value = _optional_string(values, key)
    return uuid.UUID(value) if value else None


def _context_references(value: object) -> tuple[PlanningContextReference, ...]:
    if not isinstance(value, (tuple, list)):
        raise ValueError("local runtime context_references must be a sequence")
    references: list[PlanningContextReference] = []
    for item in value:
        if not isinstance(item, (tuple, list)) or len(item) != 3:
            raise ValueError("local runtime context reference is invalid")
        context, identifier, version = item
        if not isinstance(context, str) or not isinstance(identifier, str):
            raise ValueError("local runtime context reference is invalid")
        if version is not None and not isinstance(version, str):
            raise ValueError("local runtime context reference version is invalid")
        references.append(PlanningContextReference(context, identifier, version))
    return tuple(references)
