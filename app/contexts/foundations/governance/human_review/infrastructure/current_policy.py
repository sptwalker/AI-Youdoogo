"""Behavior-preserving review policy for the current runtime."""

from app.contexts.foundations.governance.human_review.contracts.review import (
    ReviewDecision,
    ReviewRequest,
)


class CurrentHumanReviewPolicy:
    """Current capability handlers defer real side effects to later human-owned flows."""

    def decide(self, request: ReviewRequest) -> ReviewDecision:
        return ReviewDecision(
            approved=True,
            requires_human=False,
            reason="当前能力仅生成草稿、读模型或后续人工任务",
            decision_reference=request.approval_reference,
        )
