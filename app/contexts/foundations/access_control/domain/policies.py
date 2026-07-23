"""Pure role and row-visibility policies."""

from __future__ import annotations

from app.contexts.foundations.access_control.contracts import (
    PolicyDecision,
    RolePolicyRequest,
    RowPolicyRequest,
    RowVisibilityScope,
)
from app.contexts.foundations.identity.contracts import Principal

PRIVILEGED_ROW_ROLES = ("admin", "executive")


def decide_role(request: RolePolicyRequest) -> PolicyDecision:
    if request.principal.role_code in request.allowed_roles:
        return PolicyDecision(allowed=True)
    return PolicyDecision(allowed=False, reason="无权限执行此操作")


def is_privileged_role(role_code: str) -> bool:
    return role_code in PRIVILEGED_ROW_ROLES


def decide_row_visibility(request: RowPolicyRequest) -> PolicyDecision:
    principal = request.principal
    if is_privileged_role(principal.role_code):
        return PolicyDecision(allowed=True)
    if request.creator_id is not None and request.creator_id == principal.principal_id:
        return PolicyDecision(allowed=True)
    if (
        request.assignee_user_id is not None
        and request.assignee_user_id == principal.principal_id
    ):
        return PolicyDecision(allowed=True)
    if (
        request.department_id is not None
        and request.department_id == principal.department_id
    ):
        return PolicyDecision(allowed=True)
    return PolicyDecision(
        allowed=False,
        reason="资源不存在",
        conceal_resource=True,
    )


def row_visibility_scope(principal: Principal) -> RowVisibilityScope:
    if is_privileged_role(principal.role_code):
        return RowVisibilityScope(all_rows=True)
    return RowVisibilityScope(
        all_rows=False,
        creator_id=principal.principal_id,
        department_id=principal.department_id,
        assignee_user_id=principal.principal_id,
    )
