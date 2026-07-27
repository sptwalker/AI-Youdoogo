"""Request-scoped composition for AI Quality."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import run_agent
from app.contexts.foundations.governance.ai_quality.application.use_cases import (
    CompareCandidatePrompt,
    CreateEvaluationCase,
    DeleteEvaluationCase,
    ListEvaluationCases,
    ListLowScoreSamples,
    ListMyFeedback,
    RecordFeedback,
    RunEvaluation,
    SuggestPromptImprovement,
)
from app.contexts.foundations.governance.ai_quality.infrastructure.legacy_execution import (
    LangChainEvaluationJudge,
    LangChainPromptSuggestion,
    LegacyAgentEvaluationExecutor,
)
from app.contexts.foundations.governance.ai_quality.infrastructure.sqlalchemy_adapter import (
    SQLAlchemyAIQualityUnitOfWork,
    SQLAlchemyEvaluationSubject,
)
from app.llm import get_llm_for_role
from app.llm.usage import extract_usage, record_usage


class AIQualityOperations:
    """Composed AI Quality use cases for one request session."""

    def __init__(self, session: AsyncSession) -> None:
        unit = SQLAlchemyAIQualityUnitOfWork(session)
        evaluator = RunEvaluation(
            unit,
            SQLAlchemyEvaluationSubject(session),
            LegacyAgentEvaluationExecutor(session, run_agent),
            LangChainEvaluationJudge(
                session,
                llm_factory=get_llm_for_role,
                usage_extractor=extract_usage,
                usage_recorder=record_usage,
            ),
        )
        self.list_cases = ListEvaluationCases(unit)
        self.create_case = CreateEvaluationCase(unit)
        self.delete_case = DeleteEvaluationCase(unit)
        self.record_feedback = RecordFeedback(unit)
        self.list_my_feedback = ListMyFeedback(unit)
        self.list_low_score_samples = ListLowScoreSamples(unit)
        self.suggest_prompt_improvement = SuggestPromptImprovement(
            unit,
            SQLAlchemyEvaluationSubject(session),
            LangChainPromptSuggestion(
                session,
                llm_factory=get_llm_for_role,
                usage_extractor=extract_usage,
                usage_recorder=record_usage,
            ),
        )
        self.run_evaluation = evaluator
        self.compare_candidate = CompareCandidatePrompt(evaluator)


def build_ai_quality(session: AsyncSession) -> AIQualityOperations:
    return AIQualityOperations(session)
