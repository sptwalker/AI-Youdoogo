"""Evaluate, compare, record feedback, and suggest without promoting changes."""

from __future__ import annotations

import uuid

from app.contexts.foundations.governance.ai_quality.application.ports import (
    AIQualityUnitOfWork,
    EvaluationExecutorPort,
    EvaluationJudgePort,
    EvaluationSubjectPort,
    PromptSuggestionPort,
)
from app.contexts.foundations.governance.ai_quality.contracts.quality import (
    CreateEvaluationCaseCommand,
    EvaluationCaseScore,
    EvaluationCaseView,
    EvaluationResult,
    FeedbackResult,
    LowScoreSample,
    PromptImprovementSuggestion,
    RecordFeedbackCommand,
    ShadowComparisonResult,
)
from app.contexts.foundations.governance.ai_quality.domain.scoring import average_score
from app.contexts.foundations.workforce.expert_management.contracts.execution import (
    ExpertExecutionSnapshot,
)
from app.contexts.shared_kernel import ResourceNotFound, RuleViolation


class RunEvaluation:
    def __init__(
        self,
        unit: AIQualityUnitOfWork,
        subjects: EvaluationSubjectPort,
        executor: EvaluationExecutorPort,
        judge: EvaluationJudgePort,
    ) -> None:
        self._unit = unit
        self._subjects = subjects
        self._executor = executor
        self._judge = judge

    async def execute(
        self,
        role_id: uuid.UUID,
        *,
        prompt: str | None = None,
        user_id: uuid.UUID | None = None,
    ) -> EvaluationResult:
        subject = await self._subject(role_id)
        cases = await self._cases(role_id)
        return await self._run(subject, prompt or subject.prompt_template, cases, user_id)

    async def _subject(self, role_id: uuid.UUID) -> ExpertExecutionSnapshot:
        subject = await self._subjects.get(role_id)
        if subject is None:
            raise ResourceNotFound("智能体角色不存在")
        return subject

    async def _cases(self, role_id: uuid.UUID) -> tuple[EvaluationCaseView, ...]:
        cases = await self._unit.cases.list_applicable(role_id)
        if not cases:
            raise RuleViolation("该角色暂无可用评估用例，请先在评估集中添加")
        return cases

    async def _run(
        self,
        subject: ExpertExecutionSnapshot,
        prompt: str,
        cases: tuple[EvaluationCaseView, ...],
        user_id: uuid.UUID | None,
    ) -> EvaluationResult:
        scores: list[EvaluationCaseScore] = []
        for case in cases:
            output = await self._executor.execute(subject, prompt, case, user_id)
            score = await self._judge.score(case.rubric, output, user_id)
            scores.append(EvaluationCaseScore(case.name, score))
        values = tuple(item.score for item in scores)
        return EvaluationResult(subject.expert_id, average_score(values), tuple(scores))


class CompareCandidatePrompt:
    def __init__(self, evaluator: RunEvaluation) -> None:
        self._evaluator = evaluator

    async def execute(
        self,
        role_id: uuid.UUID,
        candidate_prompt: str,
        *,
        user_id: uuid.UUID | None = None,
    ) -> ShadowComparisonResult:
        baseline = await self._evaluator.execute(role_id, user_id=user_id)
        candidate = await self._evaluator.execute(
            role_id, prompt=candidate_prompt, user_id=user_id
        )
        delta = round(candidate.average_score - baseline.average_score, 3)
        return ShadowComparisonResult(
            role_id=role_id,
            baseline_average=baseline.average_score,
            candidate_average=candidate.average_score,
            delta=delta,
            improved=delta > 0,
            case_count=len(baseline.scores),
        )


class ListEvaluationCases:
    def __init__(self, unit: AIQualityUnitOfWork) -> None:
        self._unit = unit

    async def execute(self, role_id: uuid.UUID | None = None) -> tuple[EvaluationCaseView, ...]:
        return await self._unit.cases.list(role_id)


class CreateEvaluationCase:
    def __init__(self, unit: AIQualityUnitOfWork) -> None:
        self._unit = unit

    async def execute(self, command: CreateEvaluationCaseCommand) -> EvaluationCaseView:
        name = command.name.strip()
        input_text = command.input_text.strip()
        if not name or not input_text:
            raise RuleViolation("用例名称和输入必填")
        normalized = CreateEvaluationCaseCommand(
            name=name,
            role_id=command.role_id,
            input_text=input_text,
            rubric=(command.rubric or "").strip() or "产出是否准确、切题、可用。",
        )
        created = await self._unit.cases.create(normalized)
        await self._unit.commit()
        return created


class DeleteEvaluationCase:
    def __init__(self, unit: AIQualityUnitOfWork) -> None:
        self._unit = unit

    async def execute(self, case_id: uuid.UUID) -> None:
        await self._unit.cases.delete(case_id)
        await self._unit.commit()


class RecordFeedback:
    def __init__(self, unit: AIQualityUnitOfWork) -> None:
        self._unit = unit

    async def execute(self, command: RecordFeedbackCommand) -> FeedbackResult:
        if not 1 <= command.score <= 5:
            raise RuleViolation("评分需为 1~5")
        if not await self._unit.feedback.execution_exists(command.task_record_id):
            raise ResourceNotFound("执行记录不存在")
        result = await self._unit.feedback.add(command)
        await self._unit.commit()
        return result


class ListMyFeedback:
    """Return the current rater's feedback for a set of execution records (回显已评)。"""

    def __init__(self, unit: AIQualityUnitOfWork) -> None:
        self._unit = unit

    async def execute(
        self, rater_id: uuid.UUID, task_record_ids: tuple[uuid.UUID, ...]
    ) -> tuple[FeedbackResult, ...]:
        return await self._unit.feedback.mine(rater_id, task_record_ids)


class ListLowScoreSamples:
    """Return feedback evidence without exposing the repository adapter."""

    def __init__(self, unit: AIQualityUnitOfWork) -> None:
        self._unit = unit

    async def execute(
        self,
        role_id: uuid.UUID,
        *,
        threshold: int = 3,
        limit: int = 20,
    ) -> tuple[LowScoreSample, ...]:
        return await self._unit.feedback.low_scored(role_id, threshold, limit)


class SuggestPromptImprovement:
    def __init__(
        self,
        unit: AIQualityUnitOfWork,
        subjects: EvaluationSubjectPort,
        suggestions: PromptSuggestionPort,
    ) -> None:
        self._unit = unit
        self._subjects = subjects
        self._suggestions = suggestions

    async def execute(
        self,
        role_id: uuid.UUID,
        *,
        threshold: int = 3,
        limit: int = 20,
        user_id: uuid.UUID | None = None,
    ) -> PromptImprovementSuggestion:
        subject = await self._subjects.get(role_id)
        if subject is None:
            raise ResourceNotFound("智能体角色不存在")
        samples = await self._unit.feedback.low_scored(role_id, threshold, limit)
        if not samples:
            raise RuleViolation(f"该角色暂无评分≤{threshold}的反馈，无需优化")
        suggested = await self._suggestions.suggest(
            subject.prompt_template, samples, user_id
        )
        return PromptImprovementSuggestion(
            role_id=role_id,
            current_prompt=subject.prompt_template,
            suggested_prompt=suggested,
            based_on_samples=len(samples),
        )
