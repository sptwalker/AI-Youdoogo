"""Pure policy entrypoint for legacy and Context consumers."""

from app.contexts.foundations.access_control.contracts import (
    PolicyDecision,
    RolePolicyRequest,
    RowPolicyRequest,
    RowVisibilityScope,
)
from app.contexts.foundations.access_control.domain.policies import (
    decide_role as _decide_role,
)
from app.contexts.foundations.access_control.domain.policies import (
    decide_row_visibility as _decide_row_visibility,
)
from app.contexts.foundations.access_control.domain.policies import (
    is_privileged_role,
)
from app.contexts.foundations.access_control.domain.policies import (
    row_visibility_scope as _row_visibility_scope,
)
from app.contexts.foundations.identity.contracts import Principal


def decide_role(request: RolePolicyRequest) -> PolicyDecision:
    return _decide_role(request)


def decide_row_visibility(request: RowPolicyRequest) -> PolicyDecision:
    return _decide_row_visibility(request)


def visibility_scope(principal: Principal) -> RowVisibilityScope:
    return _row_visibility_scope(principal)


__all__ = [
    "decide_role",
    "decide_row_visibility",
    "is_privileged_role",
    "visibility_scope",
]
