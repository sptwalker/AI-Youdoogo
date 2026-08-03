"""Request-scoped composition for AI Quality."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.execution.agent_execution.public import run_agent
from app.contexts.foundations.governance.ai_quality.application.use_cases import (
    CompareCandidatePrompt,
    CreateEvaluationCase,
    DeleteEvaluationCase,
    ListEvaluationCases,
    ListLowScoreSamples,
    ListMyFeedback,
    RecordFeedback,
    ReviewOutput,
    RunEvaluation,
    SuggestPromptImprovement,
)
from app.contexts.foundations.governance.ai_quality.infrastructure.legacy_execution import (
    CompletionEvaluationJudge,
    CompletionPromptSuggestion,
    LegacyAgentEvaluationExecutor,
)
from app.contexts.foundations.governance.ai_quality.infrastructure.output_review import (
    AgentOutputRevision,
    LangChainOutputCritic,
    LoggingOutputReviewFailureReporter,
)
from app.contexts.foundations.governance.ai_quality.infrastructure.sqlalchemy_adapter import (
    SQLAlchemyAIQualityUnitOfWork,
    SQLAlchemyEvaluationSubject,
)
from app.contexts.foundations.governance.usage_budget.public import record_usage
from app.contexts.foundations.model_gateway.public import build_llm_completion_port

LangChainEvaluationJudge = CompletionEvaluationJudge
LangChainPromptSuggestion = CompletionPromptSuggestion


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
                port=build_llm_completion_port(),
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
                port=build_llm_completion_port(),
                usage_recorder=record_usage,
            ),
        )
        self.run_evaluation = evaluator
        self.compare_candidate = CompareCandidatePrompt(evaluator)
        self.review_output = ReviewOutput(
            LangChainOutputCritic(session),
            AgentOutputRevision(session),
            LoggingOutputReviewFailureReporter(),
        )


def build_ai_quality(session: AsyncSession) -> AIQualityOperations:
    return AIQualityOperations(session)
