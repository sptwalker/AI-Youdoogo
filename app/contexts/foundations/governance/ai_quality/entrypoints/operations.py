"""Request-scoped published AI Quality operations."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.governance.ai_quality.contracts.quality import (
    CreateEvaluationCaseCommand,
    EvaluationCaseView,
    EvaluationResult,
    FeedbackResult,
    LowScoreSample,
    PromptImprovementSuggestion,
    RecordFeedbackCommand,
    ShadowComparisonResult,
)
from app.contexts.foundations.governance.ai_quality.infrastructure.composition import (
    build_ai_quality,
)


async def list_evaluation_cases(
    session: AsyncSession,
    role_id: uuid.UUID | None = None,
) -> tuple[EvaluationCaseView, ...]:
    return await build_ai_quality(session).list_cases.execute(role_id)


async def create_evaluation_case(
    session: AsyncSession,
    command: CreateEvaluationCaseCommand,
) -> EvaluationCaseView:
    return await build_ai_quality(session).create_case.execute(command)


async def delete_evaluation_case(
    session: AsyncSession,
    case_id: uuid.UUID,
) -> None:
    await build_ai_quality(session).delete_case.execute(case_id)


async def record_feedback(
    session: AsyncSession,
    command: RecordFeedbackCommand,
) -> FeedbackResult:
    return await build_ai_quality(session).record_feedback.execute(command)


async def list_low_score_samples(
    session: AsyncSession,
    role_id: uuid.UUID,
    *,
    threshold: int = 3,
    limit: int = 20,
) -> tuple[LowScoreSample, ...]:
    return await build_ai_quality(session).list_low_score_samples.execute(
        role_id,
        threshold=threshold,
        limit=limit,
    )


async def suggest_prompt_improvement(
    session: AsyncSession,
    role_id: uuid.UUID,
    *,
    threshold: int = 3,
    limit: int = 20,
    user_id: uuid.UUID | None = None,
) -> PromptImprovementSuggestion:
    return await build_ai_quality(session).suggest_prompt_improvement.execute(
        role_id,
        threshold=threshold,
        limit=limit,
        user_id=user_id,
    )


async def run_evaluation(
    session: AsyncSession,
    role_id: uuid.UUID,
    *,
    user_id: uuid.UUID | None = None,
) -> EvaluationResult:
    return await build_ai_quality(session).run_evaluation.execute(
        role_id,
        user_id=user_id,
    )


async def compare_candidate_prompt(
    session: AsyncSession,
    role_id: uuid.UUID,
    candidate_prompt: str,
    *,
    user_id: uuid.UUID | None = None,
) -> ShadowComparisonResult:
    return await build_ai_quality(session).compare_candidate.execute(
        role_id,
        candidate_prompt,
        user_id=user_id,
    )
