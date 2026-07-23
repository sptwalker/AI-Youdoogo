"""Published, framework-independent Access Control decisions."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.contexts.foundations.identity.contracts import Principal


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    """A policy answer with optional concealment semantics for denied reads."""

    allowed: bool
    reason: str = ""
    conceal_resource: bool = False


@dataclass(frozen=True, slots=True)
class RolePolicyRequest:
    principal: Principal
    allowed_roles: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RowPolicyRequest:
    principal: Principal
    creator_id: uuid.UUID | None
    department_id: uuid.UUID | None = None
    assignee_user_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class ResourceReadPolicyRequest:
    principal: Principal
    resource_type: str
    resource_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class RowVisibilityScope:
    """Pure row-query intent translated by each persistence adapter."""

    all_rows: bool
    creator_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    assignee_user_id: uuid.UUID | None = None
