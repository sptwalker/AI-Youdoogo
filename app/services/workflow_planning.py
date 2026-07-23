"""One-way compatibility facade for the Work Planning bounded context."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.execution.work_planning.application.use_cases import (
    MAX_PLAN_STEPS,
    PlanWorkApplication,
    parse_workflow_plan,
    requires_human_review,
)
from app.contexts.foundations.execution.work_planning.contracts.planning import (
    PlanWorkRequest,
    WorkIntent,
)
from app.contexts.foundations.execution.work_planning.infrastructure.langchain_planner import (
    LangChainPlanningModelAdapter,
)
from app.llm import get_llm_for_role
from app.models.task import TaskCard
from app.services import task_service

logger = logging.getLogger(__name__)

MAX_STEPS = MAX_PLAN_STEPS


def is_red_line(skill: str) -> bool:
    return requires_human_review(skill)


@dataclass
class PlanStep:
    no: int
    title: str
    skill: str
    instruction: str
    depends_on: list[int] = field(default_factory=list)


def parse_plan(raw: str) -> list[PlanStep] | None:
    request = PlanWorkRequest(
        WorkIntent(request="legacy planning parse", creator_id=uuid.UUID(int=0))
    )
    result = parse_workflow_plan(raw, request)
    if result.plan is None:
        return None
    return [
        PlanStep(
            no=step.number,
            title=step.title,
            skill=step.capability_key,
            instruction=step.instruction,
            depends_on=list(step.depends_on),
        )
        for step in result.plan.steps
    ]


async def plan(
    db: AsyncSession,
    request: str,
    *,
    llm_factory: Callable[..., Any] = get_llm_for_role,
) -> list[PlanStep] | None:
    del db
    if not request or not request.strip():
        return None
    try:
        result = await PlanWorkApplication(
            LangChainPlanningModelAdapter(llm_factory)
        ).execute(
            PlanWorkRequest(
                WorkIntent(request=request.strip(), creator_id=uuid.UUID(int=0))
            )
        )
        if result.plan is None:
            return None
        return [
            PlanStep(
                step.number,
                step.title,
                step.capability_key,
                step.instruction,
                list(step.depends_on),
            )
            for step in result.plan.steps
        ]
    except Exception:  # noqa: BLE001
        logger.warning("任务编排规划失败，退回单步执行", exc_info=True)
        return None


async def build_steps(
    db: AsyncSession,
    parent_id: uuid.UUID,
    steps: list[PlanStep],
    *,
    creator_id: uuid.UUID,
    assignee_agent_id: uuid.UUID | None = None,
) -> list[TaskCard]:
    no_to_id: dict[int, uuid.UUID] = {}
    no_to_card: dict[int, TaskCard] = {}
    for step in sorted(steps, key=lambda item: item.no):
        card = await task_service.create_task(
            db,
            title=step.title,
            task_type=step.skill,
            creator_id=creator_id,
            assignee_agent_id=assignee_agent_id,
            parent_id=parent_id,
            step_no=step.no,
            payload={
                "instruction": step.instruction,
                "skill": step.skill,
                "red_line": is_red_line(step.skill),
            },
        )
        no_to_id[step.no] = card.id
        no_to_card[step.no] = card
    for step in steps:
        no_to_card[step.no].depends_on = [str(no_to_id[dep]) for dep in step.depends_on]
    await db.commit()
    cards = [no_to_card[step.no] for step in sorted(steps, key=lambda item: item.no)]
    for card in cards:
        await db.refresh(card)
    return cards
