"""Access-owned persistence and caller-owned visibility ports."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime
from types import TracebackType
from typing import Protocol, Self

from app.contexts.foundations.access_control.contracts import (
    PolicyDecision,
    ResourceReadPolicyRequest,
    RolePolicyRequest,
    RowPolicyRequest,
    RowVisibilityScope,
)
from app.contexts.foundations.access_control.domain.models import (
    GrantTarget,
    ResourceGrantRecord,
)
from app.contexts.foundations.identity.contracts import Principal


class GrantRepository(Protocol):
    async def get(self, grant_id: uuid.UUID) -> ResourceGrantRecord | None: ...

    async def add(self, grant: ResourceGrantRecord) -> None: ...

    async def save(self, grant: ResourceGrantRecord) -> None: ...

    async def list_records(
        self,
        *,
        resource_type: str | None,
        grantee_id: uuid.UUID | None,
    ) -> list[ResourceGrantRecord]: ...

    async def find_for_targets(
        self,
        *,
        resource_type: str,
        targets: tuple[GrantTarget, ...],
    ) -> list[ResourceGrantRecord]: ...


class AccessControlUnitOfWork(Protocol):
    @property
    def grants(self) -> GrantRepository: ...

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


AccessControlUnitOfWorkFactory = Callable[[], AccessControlUnitOfWork]


class DepartmentHierarchyPort(Protocol):
    async def ancestors_of(self, department_id: uuid.UUID | None) -> tuple[uuid.UUID, ...]: ...


class KnowledgeVisibilityPort(Protocol):
    async def visible_ids(
        self,
        *,
        department_id: uuid.UUID | None,
        is_admin: bool,
        extra_knowledge_ids: tuple[uuid.UUID, ...],
    ) -> tuple[uuid.UUID, ...]: ...


class IdentifierPort(Protocol):
    def new_id(self) -> uuid.UUID: ...


class Clock(Protocol):
    def now(self) -> datetime: ...


class PolicyDecisionPort(Protocol):
    """Pure contract consumed by business contexts instead of ORM-aware services."""

    def decide_role(self, request: RolePolicyRequest) -> PolicyDecision: ...

    def decide_row_visibility(self, request: RowPolicyRequest) -> PolicyDecision: ...

    def row_visibility_scope(self, principal: Principal) -> RowVisibilityScope: ...

    async def decide_resource_read(
        self, request: ResourceReadPolicyRequest
    ) -> PolicyDecision: ...
