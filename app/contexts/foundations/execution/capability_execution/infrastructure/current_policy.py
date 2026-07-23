"""Behavior-preserving policy adapters for the current capability runtime."""

from app.contexts.foundations.execution.capability_catalog.contracts.definition import (
    CapabilityDefinition,
)
from app.contexts.foundations.execution.capability_execution.application.ports import (
    ApprovalDecision,
    AuthorizationDecision,
)
from app.contexts.foundations.execution.capability_execution.contracts.execution import (
    CapabilityExecutionRequest,
)
from app.contexts.foundations.governance.human_review.contracts.review import (
    ReviewRequest,
    ReviewRisk,
)
from app.contexts.foundations.governance.human_review.public import evaluate_review


class CurrentCapabilityAuthorization:
    """Preserve current role/tool gating while exposing an explicit policy seam."""

    async def authorize(
        self, request: CapabilityExecutionRequest, definition: CapabilityDefinition
    ) -> AuthorizationDecision:
        del request, definition
        return AuthorizationDecision(allowed=True)


class CurrentCapabilityApproval:
    """Current capabilities produce drafts/read models or later human-review records."""

    async def check(
        self, request: CapabilityExecutionRequest, definition: CapabilityDefinition
    ) -> ApprovalDecision:
        decision = evaluate_review(
            ReviewRequest(
                action=definition.key,
                target_type="capability",
                target_id=definition.key,
                principal_id=request.principal.principal_id,
                risk=ReviewRisk(definition.risk.value),
                policy_version=definition.version,
                approval_reference=request.approval_reference,
            )
        )
        return ApprovalDecision(approved=decision.approved, reason=decision.reason)
