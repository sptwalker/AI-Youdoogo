"""Stable Human Review decision operation."""

from app.contexts.foundations.governance.human_review.application.use_cases import (
    EvaluateHumanReview,
)
from app.contexts.foundations.governance.human_review.contracts.review import (
    ReviewDecision,
    ReviewRequest,
)
from app.contexts.foundations.governance.human_review.infrastructure.current_policy import (
    CurrentHumanReviewPolicy,
)


def evaluate_review(request: ReviewRequest) -> ReviewDecision:
    return EvaluateHumanReview(CurrentHumanReviewPolicy()).execute(request)
