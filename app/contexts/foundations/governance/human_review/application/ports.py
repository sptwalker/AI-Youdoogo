"""Human Review policy port."""

from typing import Protocol

from app.contexts.foundations.governance.human_review.contracts.review import (
    ReviewDecision,
    ReviewRequest,
)


class HumanReviewPolicyPort(Protocol):
    def decide(self, request: ReviewRequest) -> ReviewDecision: ...
