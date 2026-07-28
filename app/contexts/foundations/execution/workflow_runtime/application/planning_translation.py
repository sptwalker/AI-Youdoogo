"""Anti-corruption translation from Planning v1 to Runtime v2."""

from __future__ import annotations

import hashlib
import json

from app.contexts.foundations.execution.work_planning.contracts.planning import (
    WorkflowPlan,
)
from app.contexts.foundations.execution.workflow_runtime.contracts.runtime import (
    StartWorkflowCommand,
    WorkflowLaunchStep,
)
from app.contexts.foundations.execution.workflow_runtime.contracts.runtime_v2 import (
    RuntimeExecutorRef,
    RuntimeStepSubmissionV2,
    RuntimeSubmissionV2,
)

DEFAULT_WORKFLOW_TYPE = "durable_dag"


def planning_to_start_command(plan: WorkflowPlan) -> StartWorkflowCommand:
    """Translate the Planning contract into the durable Runtime v1 launch command."""
    intent = plan.intent
    return StartWorkflowCommand(
        creator_id=intent.creator_id,
        request=intent.request,
        steps=tuple(
            WorkflowLaunchStep(
                number=step.number,
                title=step.title,
                capability_key=step.capability_key,
                instruction=step.instruction,
                depends_on=step.depends_on,
            )
            for step in plan.steps
        ),
        title=intent.title,
        assignee_expert_id=intent.assignee_expert_id,
    )


def planning_to_runtime_v2(
    plan: WorkflowPlan,
    *,
    business_key: str | None = None,
    workflow_type: str = DEFAULT_WORKFLOW_TYPE,
) -> RuntimeSubmissionV2:
    """Deterministically translate an immutable Planning v1 plan to Runtime v2."""
    resolved_business_key = business_key or _derived_business_key(plan)
    steps = tuple(
        RuntimeStepSubmissionV2(
            business_key=_step_key(step.number),
            executor_ref=RuntimeExecutorRef(
                namespace="capability",
                key=step.capability_key,
            ),
            input_data=(
                ("step_number", step.number),
                ("title", step.title),
                ("instruction", step.instruction),
            ),
            depends_on=tuple(_step_key(number) for number in step.depends_on),
        )
        for step in sorted(plan.steps, key=lambda item: item.number)
    )
    intent = plan.intent
    return RuntimeSubmissionV2(
        business_key=resolved_business_key,
        workflow_type=workflow_type,
        input_data=(
            ("request", intent.request),
            ("title", intent.title),
            ("creator_id", str(intent.creator_id)),
            (
                "assignee_expert_id",
                str(intent.assignee_expert_id) if intent.assignee_expert_id else None,
            ),
            (
                "context_references",
                tuple(
                    (reference.context, reference.identifier, reference.version)
                    for reference in intent.context_references
                ),
            ),
            ("planning_contract_version", plan.contract_version),
        ),
        steps=steps,
    )


def _step_key(number: int) -> str:
    return f"step:{number}"


def _derived_business_key(plan: WorkflowPlan) -> str:
    intent = plan.intent
    canonical = {
        "contract_version": plan.contract_version,
        "intent": {
            "request": intent.request,
            "title": intent.title,
            "creator_id": str(intent.creator_id),
            "assignee_expert_id": (
                str(intent.assignee_expert_id) if intent.assignee_expert_id else None
            ),
            "context_references": [
                {
                    "context": reference.context,
                    "identifier": reference.identifier,
                    "version": reference.version,
                }
                for reference in intent.context_references
            ],
        },
        "steps": [
            {
                "number": step.number,
                "title": step.title,
                "capability_key": step.capability_key,
                "instruction": step.instruction,
                "depends_on": list(step.depends_on),
            }
            for step in sorted(plan.steps, key=lambda item: item.number)
        ],
    }
    encoded = json.dumps(
        canonical,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"planning-v1:{hashlib.sha256(encoded).hexdigest()}"
