"""One-way compatibility facade for AI Quality feedback and suggestions."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.governance.ai_quality.application.use_cases import (
    RecordFeedback,
    SuggestPromptImprovement,
)
from app.contexts.foundations.governance.ai_quality.contracts.quality import (
    RecordFeedbackCommand,
)
from app.contexts.foundations.governance.ai_quality.infrastructure.legacy_execution import (
    CompletionPromptSuggestion,
)
from app.contexts.foundations.governance.ai_quality.infrastructure.sqlalchemy_adapter import (
    SQLAlchemyAIQualityUnitOfWork,
    SQLAlchemyEvaluationSubject,
    get_feedback_record,
)
from app.contexts.foundations.model_gateway.public import build_llm_completion_port
from app.llm.usage import record_usage
from app.models.feedback import AgentFeedback


async def add_feedback(
    db: AsyncSession,
    *,
    task_record_id: uuid.UUID,
    rater_id: uuid.UUID,
    score: int,
    comment: str | None = None,
) -> AgentFeedback:
    result = await RecordFeedback(SQLAlchemyAIQualityUnitOfWork(db)).execute(
        RecordFeedbackCommand(
            task_record_id=task_record_id,
            rater_id=rater_id,
            score=score,
            comment=comment,
        )
    )
    return await get_feedback_record(db, result.feedback_id)


async def _collect_low_scored(
    db: AsyncSession, role_id: uuid.UUID, threshold: int, limit: int
) -> list[tuple[str, int, str | None]]:
    samples = await SQLAlchemyAIQualityUnitOfWork(db).feedback.low_scored(
        role_id, threshold, limit
    )
    return [(sample.output, sample.score, sample.comment) for sample in samples]


async def optimize_prompt(
    db: AsyncSession,
    role_id: uuid.UUID,
    *,
    threshold: int = 3,
    limit: int = 20,
    user_id: uuid.UUID | None = None,
) -> dict[str, object]:
    suggestion = await SuggestPromptImprovement(
        SQLAlchemyAIQualityUnitOfWork(db),
        SQLAlchemyEvaluationSubject(db),
        CompletionPromptSuggestion(
            db,
            port=build_llm_completion_port(),
            usage_recorder=record_usage,
        ),
    ).execute(
        role_id,
        threshold=threshold,
        limit=limit,
        user_id=user_id,
    )
    return {
        "role_id": str(suggestion.role_id),
        "current_prompt": suggestion.current_prompt,
        "suggested_prompt": suggestion.suggested_prompt,
        "based_on_samples": suggestion.based_on_samples,
    }
