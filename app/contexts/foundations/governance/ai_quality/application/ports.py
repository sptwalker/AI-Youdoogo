"""AI Quality-owned repositories and external evaluation ports."""

from __future__ import annotations

import uuid
from typing import Protocol

from app.contexts.foundations.governance.ai_quality.contracts.quality import (
    CreateEvaluationCaseCommand,
    EvaluationCaseView,
    FeedbackResult,
    LowScoreSample,
    RecordFeedbackCommand,
)
from app.contexts.foundations.workforce.expert_management.contracts.execution import (
    ExpertExecutionSnapshot,
)


class EvaluationCaseRepositoryPort(Protocol):
    async def list_applicable(
        self, role_id: uuid.UUID
    ) -> tuple[EvaluationCaseView, ...]: ...

    async def list(self, role_id: uuid.UUID | None) -> tuple[EvaluationCaseView, ...]: ...

    async def create(self, command: CreateEvaluationCaseCommand) -> EvaluationCaseView: ...

    async def delete(self, case_id: uuid.UUID) -> None: ...


class FeedbackRepositoryPort(Protocol):
    async def execution_exists(self, task_record_id: uuid.UUID) -> bool: ...

    async def add(self, command: RecordFeedbackCommand) -> FeedbackResult: ...

    async def low_scored(
        self, role_id: uuid.UUID, threshold: int, limit: int
    ) -> tuple[LowScoreSample, ...]: ...


class EvaluationSubjectPort(Protocol):
    async def get(self, role_id: uuid.UUID) -> ExpertExecutionSnapshot | None: ...


class AIQualityUnitOfWork(Protocol):
    cases: EvaluationCaseRepositoryPort
    feedback: FeedbackRepositoryPort

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


class EvaluationExecutorPort(Protocol):
    async def execute(
        self,
        subject: ExpertExecutionSnapshot,
        prompt: str,
        case: EvaluationCaseView,
        user_id: uuid.UUID | None,
    ) -> str: ...


class EvaluationJudgePort(Protocol):
    async def score(
        self, rubric: str, output: str, user_id: uuid.UUID | None
    ) -> int: ...


class PromptSuggestionPort(Protocol):
    async def suggest(
        self,
        current_prompt: str,
        samples: tuple[LowScoreSample, ...],
        user_id: uuid.UUID | None,
    ) -> str: ...
