"""Planning policy that produces a validated plan without persistence access."""

from __future__ import annotations

import json
import re

from app.contexts.foundations.execution.work_planning.application.ports import (
    PlanningModelPort,
)
from app.contexts.foundations.execution.work_planning.contracts.planning import (
    PlanWorkRequest,
    PlanWorkResult,
    WorkflowPlan,
    WorkflowPlanStep,
)

MAX_PLAN_STEPS = 16
# knowledge_index：内部知识沉淀属「辅助执行」（可检索复用·可软删·非对外发布）→ 免真人停点。
AUTOMATIC_CAPABILITIES: frozenset[str] = frozenset(
    {"data_query", "deliver", "knowledge_index"}
)


def requires_human_review(capability_key: str) -> bool:
    return capability_key not in AUTOMATIC_CAPABILITIES


def parse_workflow_plan(raw: str, request: PlanWorkRequest) -> PlanWorkResult:
    """Translate untrusted model JSON into the immutable published plan."""
    try:
        data = json.loads(_strip_fence(raw))
    except (json.JSONDecodeError, TypeError):
        return PlanWorkResult(None, "invalid_json")
    if not isinstance(data, dict) or not data.get("multi"):
        return PlanWorkResult(None, "single_action")
    raw_steps = data.get("steps")
    if not isinstance(raw_steps, list) or len(raw_steps) < 2:
        return PlanWorkResult(None, "insufficient_steps")
    steps: list[WorkflowPlanStep] = []
    for item in raw_steps[:MAX_PLAN_STEPS]:
        if not isinstance(item, dict):
            return PlanWorkResult(None, "invalid_step")
        number = item.get("no")
        title = item.get("title")
        capability = item.get("skill") or "other"
        instruction = item.get("instruction") or title
        dependencies = item.get("depends_on") or []
        if (
            not isinstance(number, int)
            or not isinstance(title, str)
            or not isinstance(capability, str)
            or not isinstance(instruction, str)
            or not isinstance(dependencies, list)
            or not all(isinstance(dependency, int) for dependency in dependencies)
        ):
            return PlanWorkResult(None, "invalid_step")
        try:
            steps.append(
                WorkflowPlanStep(
                    number=number,
                    title=title.strip(),
                    capability_key=capability.strip(),
                    instruction=instruction.strip(),
                    depends_on=tuple(dependencies),
                )
            )
        except ValueError:
            return PlanWorkResult(None, "invalid_step")
    try:
        return PlanWorkResult(WorkflowPlan(request.intent, tuple(steps)))
    except ValueError as exc:
        return PlanWorkResult(None, str(exc))


class PlanWorkApplication:
    """Ask for a proposal and validate it; never persists runtime or task state."""

    def __init__(self, model: PlanningModelPort) -> None:
        self._model = model

    async def execute(self, request: PlanWorkRequest) -> PlanWorkResult:
        raw = await self._model.propose(request.intent)
        return parse_workflow_plan(raw, request)


def _strip_fence(raw: str) -> str:
    text = raw.strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    return match.group(0) if match else text
