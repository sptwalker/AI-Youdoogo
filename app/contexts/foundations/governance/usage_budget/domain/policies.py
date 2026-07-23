"""Pure authorization and threshold-crossing policies."""

from app.contexts.foundations.governance.usage_budget.contracts.usage import (
    BudgetPolicy,
    UsageAuthorizationDecision,
)


def authorize_usage(
    policy: BudgetPolicy, current_tokens: int
) -> UsageAuthorizationDecision:
    denied = (
        policy.daily_token_budget > 0
        and policy.hard_limit
        and current_tokens >= policy.daily_token_budget
    )
    if denied:
        return UsageAuthorizationDecision(
            allowed=False,
            current_tokens=current_tokens,
            daily_token_budget=policy.daily_token_budget,
            code="budget_exceeded",
            reason="当日 LLM token 预算已耗尽",
        )
    return UsageAuthorizationDecision(
        allowed=True,
        current_tokens=current_tokens,
        daily_token_budget=policy.daily_token_budget,
    )


def crossed_budget(before: int, after: int, budget: int) -> bool:
    return budget > 0 and before <= budget < after
