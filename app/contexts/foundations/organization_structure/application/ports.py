"""Organization-owned persistence and cross-context query ports."""

from __future__ import annotations

import uuid
from datetime import datetime
from types import TracebackType
from typing import Protocol, Self

from app.contexts.foundations.organization_structure.application.contracts import (
    ExternalDepartmentRecord,
    ExternalUserRecord,
    TemplateExpertSpec,
)
from app.contexts.foundations.organization_structure.domain.models import DepartmentNode
from app.contexts.foundations.workforce.expert_management.contracts.roster import (
    DepartmentExpertCount,
    ExpertRosterSnapshot,
)


class DepartmentRepository(Protocol):
    async def get(self, department_id: uuid.UUID) -> DepartmentNode | None: ...

    async def get_company_root(self) -> DepartmentNode | None: ...

    async def get_by_code(self, code: str) -> DepartmentNode | None: ...

    async def get_by_parent_name(
        self, parent_id: uuid.UUID, name: str
    ) -> DepartmentNode | None: ...

    async def get_by_external_id(self, external_id: str) -> DepartmentNode | None: ...

    async def list_nodes(self) -> list[DepartmentNode]: ...

    async def has_active_child(self, department_id: uuid.UUID) -> bool: ...

    async def add(self, department: DepartmentNode) -> None: ...

    async def save(self, department: DepartmentNode) -> None: ...


class OrganizationSourceChangePort(Protocol):
    async def publish_organization_changed(self, department_id: uuid.UUID) -> None: ...


class OrganizationUnitOfWork(Protocol):
    @property
    def departments(self) -> DepartmentRepository: ...

    @property
    def source_changes(self) -> OrganizationSourceChangePort: ...

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    async def flush(self) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


class OrganizationUnitOfWorkFactory(Protocol):
    def __call__(self) -> OrganizationUnitOfWork: ...


class ExpertRosterPort(Protocol):
    async def list_department_roster(
        self, department_id: uuid.UUID
    ) -> tuple[ExpertRosterSnapshot, ...]: ...

    async def count_by_department(
        self, *, include_personal: bool
    ) -> tuple[DepartmentExpertCount, ...]: ...

    async def has_department_assignment(self, department_id: uuid.UUID) -> bool: ...

    async def seed_expert(self, spec: TemplateExpertSpec) -> ExpertRosterSnapshot: ...


class IdentityDirectoryPort(Protocol):
    async def user_exists(self, user_id: uuid.UUID) -> bool: ...


class ExternalOrganizationDirectoryPort(Protocol):
    async def list_departments(self) -> tuple[ExternalDepartmentRecord, ...]: ...

    async def list_users(
        self, department_external_id: str
    ) -> tuple[ExternalUserRecord, ...]: ...


class ExternalIdentitySyncPort(Protocol):
    async def sync_user(
        self, user: ExternalUserRecord, *, department_id: uuid.UUID
    ) -> bool: ...


class DepartmentDiscussionPort(Protocol):
    async def create_department_channel(
        self, *, department_id: uuid.UUID, department_name: str
    ) -> None: ...


class IdentifierPort(Protocol):
    def new_id(self) -> uuid.UUID: ...


class Clock(Protocol):
    def now(self) -> datetime: ...
