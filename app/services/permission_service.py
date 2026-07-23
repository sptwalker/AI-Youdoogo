"""Compatibility facade for Access Control policy decisions."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.access_control.contracts import (
    ResourceReadPolicyRequest,
    RolePolicyRequest,
    RowPolicyRequest,
)
from app.contexts.foundations.access_control.entrypoints import operations, policy
from app.contexts.foundations.identity.contracts import Principal, PrincipalType
from app.contexts.shared_kernel import PermissionDenied, ResourceNotFound

if TYPE_CHECKING:
    from app.models.system import SysUser

_MISSING_ID = uuid.UUID(int=0)


def _principal(user: SysUser) -> Principal:
    return Principal(
        principal_type=PrincipalType.USER,
        principal_id=user.id or _MISSING_ID,
        role_code=user.role_code,
        department_id=user.department_id,
        is_active=user.is_active,
    )


def check_role(user: SysUser, *roles: str) -> None:
    decision = policy.decide_role(
        RolePolicyRequest(principal=_principal(user), allowed_roles=tuple(roles))
    )
    if not decision.allowed:
        raise PermissionDenied(decision.reason)


def is_privileged(user: SysUser) -> bool:
    return policy.is_privileged_role(user.role_code)


def can_see_row(
    user: SysUser,
    *,
    creator_id: uuid.UUID | None,
    department_id: uuid.UUID | None = None,
    assignee_user_id: uuid.UUID | None = None,
) -> bool:
    decision = policy.decide_row_visibility(
        RowPolicyRequest(
            principal=_principal(user),
            creator_id=creator_id,
            department_id=department_id,
            assignee_user_id=assignee_user_id,
        )
    )
    return decision.allowed


def assert_can_see(
    user: SysUser,
    *,
    creator_id: uuid.UUID | None,
    department_id: uuid.UUID | None = None,
    assignee_user_id: uuid.UUID | None = None,
) -> None:
    decision = policy.decide_row_visibility(
        RowPolicyRequest(
            principal=_principal(user),
            creator_id=creator_id,
            department_id=department_id,
            assignee_user_id=assignee_user_id,
        )
    )
    if not decision.allowed:
        raise ResourceNotFound(decision.reason)


def row_filter(model: Any, user: SysUser) -> Any | None:
    """Translate a pure visibility scope into the legacy SQLAlchemy query."""
    scope = policy.visibility_scope(_principal(user))
    if scope.all_rows:
        return None
    conds = [model.creator_id == scope.creator_id]
    if scope.department_id is not None and hasattr(model, "department_id"):
        conds.append(model.department_id == scope.department_id)
    if hasattr(model, "assignee_user_id"):
        conds.append(model.assignee_user_id == scope.assignee_user_id)
    return or_(*conds)


async def visible_kb_ids(db: AsyncSession, user: SysUser) -> list[uuid.UUID]:
    ids = await operations.visible_knowledge_ids(db, principal=_principal(user))
    return list(ids)


async def can_read_resource(
    db: AsyncSession,
    user: SysUser,
    resource_type: str,
    resource_id: uuid.UUID,
) -> bool:
    decision = await operations.decide_resource_read(
        db,
        ResourceReadPolicyRequest(
            principal=_principal(user),
            resource_type=resource_type,
            resource_id=resource_id,
        ),
    )
    return decision.allowed
