"""Published Work Planning operations."""

from app.contexts.foundations.execution.work_planning.application.use_cases import (
    PlanWorkApplication,
)
from app.contexts.foundations.execution.work_planning.contracts.planning import (
    PlanWorkRequest,
    PlanWorkResult,
)
from app.contexts.foundations.execution.work_planning.infrastructure.langchain_planner import (
    CompletionPlanningModelAdapter,
)
from app.contexts.foundations.model_gateway.public import build_local_llm_completion_port


async def plan_work(request: PlanWorkRequest) -> PlanWorkResult:
    """Propose and validate a workflow plan without persisting runtime state."""
    return await PlanWorkApplication(
        CompletionPlanningModelAdapter(build_local_llm_completion_port())
    ).execute(request)
