"""Framework-independent work intent and workflow plan contracts."""

from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PlanningContextReference:
    context: str
    identifier: str
    version: str | None = None


@dataclass(frozen=True, slots=True)
class WorkIntent:
    request: str
    creator_id: uuid.UUID
    title: str | None = None
    assignee_expert_id: uuid.UUID | None = None
    context_references: tuple[PlanningContextReference, ...] = ()

    def __post_init__(self) -> None:
        if not self.request.strip():
            raise ValueError("work intent request must not be blank")


@dataclass(frozen=True, slots=True)
class WorkflowPlanStep:
    number: int
    title: str
    capability_key: str
    instruction: str
    depends_on: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if self.number < 0:
            raise ValueError("workflow plan step number must be non-negative")
        if not self.title.strip():
            raise ValueError("workflow plan step title must not be blank")
        if not self.capability_key.strip():
            raise ValueError("workflow plan capability key must not be blank")
        if not self.instruction.strip():
            raise ValueError("workflow plan instruction must not be blank")
        if self.number in self.depends_on:
            raise ValueError("workflow plan step cannot depend on itself")


@dataclass(frozen=True, slots=True)
class WorkflowPlan:
    intent: WorkIntent
    steps: tuple[WorkflowPlanStep, ...]
    contract_version: int = 1

    def __post_init__(self) -> None:
        if self.contract_version != 1:
            raise ValueError("unsupported workflow plan contract version")
        numbers = tuple(step.number for step in self.steps)
        if len(numbers) != len(set(numbers)):
            raise ValueError("workflow plan step numbers must be unique")
        known = set(numbers)
        if any(dep not in known for step in self.steps for dep in step.depends_on):
            raise ValueError("workflow plan dependency references an unknown step")
        if _has_cycle(self.steps):
            raise ValueError("workflow plan must be acyclic")


@dataclass(frozen=True, slots=True)
class PlanWorkRequest:
    intent: WorkIntent


@dataclass(frozen=True, slots=True)
class PlanWorkResult:
    plan: WorkflowPlan | None
    reason: str | None = None


def _has_cycle(steps: tuple[WorkflowPlanStep, ...]) -> bool:
    by_number = {step.number: step for step in steps}
    colors: dict[int, int] = {}

    def visit(number: int) -> bool:
        colors[number] = 1
        for dependency in by_number[number].depends_on:
            state = colors.get(dependency, 0)
            if state == 1 or (state == 0 and visit(dependency)):
                return True
        colors[number] = 2
        return False

    return any(colors.get(number, 0) == 0 and visit(number) for number in by_number)
