"""Pure evaluation, feedback, and suggestion values."""

from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EvaluationCaseView:
    case_id: uuid.UUID
    name: str
    role_id: uuid.UUID | None
    input_text: str
    rubric: str
    is_active: bool = True


@dataclass(frozen=True, slots=True)
class CreateEvaluationCaseCommand:
    name: str
    input_text: str
    rubric: str | None = None
    role_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class EvaluationCaseScore:
    case_name: str
    score: int


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    role_id: uuid.UUID
    average_score: float
    scores: tuple[EvaluationCaseScore, ...]


@dataclass(frozen=True, slots=True)
class ShadowComparisonResult:
    role_id: uuid.UUID
    baseline_average: float
    candidate_average: float
    delta: float
    improved: bool
    case_count: int


@dataclass(frozen=True, slots=True)
class RecordFeedbackCommand:
    task_record_id: uuid.UUID
    rater_id: uuid.UUID
    score: int
    comment: str | None = None


@dataclass(frozen=True, slots=True)
class FeedbackResult:
    feedback_id: uuid.UUID
    task_record_id: uuid.UUID
    rater_id: uuid.UUID
    score: int
    comment: str | None = None


@dataclass(frozen=True, slots=True)
class LowScoreSample:
    output: str
    score: int
    comment: str | None


@dataclass(frozen=True, slots=True)
class PromptImprovementSuggestion:
    role_id: uuid.UUID
    current_prompt: str
    suggested_prompt: str
    based_on_samples: int
