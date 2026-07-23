"""Return review decisions without mutating the reviewed source."""

from app.contexts.foundations.governance.human_review.application.ports import (
    HumanReviewPolicyPort,
)
from app.contexts.foundations.governance.human_review.contracts.review import (
    ReviewDecision,
    ReviewRequest,
)


class EvaluateHumanReview:
    def __init__(self, policy: HumanReviewPolicyPort) -> None:
        self._policy = policy

    def execute(self, request: ReviewRequest) -> ReviewDecision:
        return self._policy.decide(request)
