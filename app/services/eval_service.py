"""One-way compatibility facade for AI Quality evaluation use cases."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.governance.ai_quality.application.use_cases import (
    CompareCandidatePrompt,
    CreateEvaluationCase,
    DeleteEvaluationCase,
    ListEvaluationCases,
    RunEvaluation,
)
from app.contexts.foundations.governance.ai_quality.contracts.quality import (
    CreateEvaluationCaseCommand,
)
from app.contexts.foundations.governance.ai_quality.domain.scoring import (
    judge_score as judge_score,
)
from app.contexts.foundations.governance.ai_quality.infrastructure.legacy_execution import (
    CallbackEvaluationJudge,
    LangChainEvaluationJudge,
    LegacyAgentEvaluationExecutor,
)
from app.contexts.foundations.governance.ai_quality.infrastructure.sqlalchemy_adapter import (
    SQLAlchemyAIQualityUnitOfWork,
    SQLAlchemyEvaluationSubject,
)
from app.llm import get_llm_for_role
from app.llm.usage import extract_usage, record_usage
from app.models.agent import AgentRole, AgentTaskRecord


async def _run_agent(
    db: AsyncSession, role: AgentRole, **kwargs: Any
) -> AgentTaskRecord:
    from app.agents.base import run_agent

    return await run_agent(db, role, **kwargs)


async def _judge(
    db: AsyncSession,
    rubric: str,
    output: str,
    user_id: uuid.UUID | None,
) -> int:
    return await LangChainEvaluationJudge(
        db,
        llm_factory=get_llm_for_role,
        usage_extractor=extract_usage,
        usage_recorder=record_usage,
    ).score(rubric, output, user_id)


def _evaluator(db: AsyncSession) -> RunEvaluation:
    unit = SQLAlchemyAIQualityUnitOfWork(db)
    return RunEvaluation(
        unit,
        SQLAlchemyEvaluationSubject(db),
        LegacyAgentEvaluationExecutor(db, _run_agent),
        CallbackEvaluationJudge(db, _judge),
    )


async def run_eval(
    db: AsyncSession,
    role_id: uuid.UUID,
    *,
    prompt: str | None = None,
    user_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    result = await _evaluator(db).execute(
        role_id, prompt=prompt, user_id=user_id
    )
    return {
        "role_id": str(result.role_id),
        "avg": result.average_score,
        "count": len(result.scores),
        "details": [
            {"case": score.case_name, "score": score.score} for score in result.scores
        ],
    }


async def shadow_compare(
    db: AsyncSession,
    role_id: uuid.UUID,
    candidate_prompt: str,
    *,
    user_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    result = await CompareCandidatePrompt(_evaluator(db)).execute(
        role_id, candidate_prompt, user_id=user_id
    )
    return {
        "role_id": str(result.role_id),
        "baseline_avg": result.baseline_average,
        "candidate_avg": result.candidate_average,
        "delta": result.delta,
        "improved": result.improved,
        "count": result.case_count,
    }


async def list_cases(
    db: AsyncSession, role_id: uuid.UUID | None = None
) -> list[dict[str, Any]]:
    cases = await ListEvaluationCases(SQLAlchemyAIQualityUnitOfWork(db)).execute(role_id)
    return [
        {
            "id": str(case.case_id),
            "name": case.name,
            "role_id": str(case.role_id) if case.role_id else None,
            "input_text": case.input_text,
            "rubric": case.rubric,
            "is_active": case.is_active,
        }
        for case in cases
    ]


async def create_case(db: AsyncSession, data: dict[str, Any]) -> dict[str, Any]:
    created = await CreateEvaluationCase(SQLAlchemyAIQualityUnitOfWork(db)).execute(
        CreateEvaluationCaseCommand(
            name=str(data.get("name") or ""),
            role_id=data.get("role_id"),
            input_text=str(data.get("input_text") or ""),
            rubric=data.get("rubric"),
        )
    )
    return {"id": str(created.case_id), "name": created.name}


async def delete_case(db: AsyncSession, case_id: uuid.UUID) -> None:
    await DeleteEvaluationCase(SQLAlchemyAIQualityUnitOfWork(db)).execute(case_id)
