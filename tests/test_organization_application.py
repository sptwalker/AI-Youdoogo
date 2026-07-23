"""Organization Structure application tests without ORM or framework dependencies."""

from __future__ import annotations

import uuid
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from types import TracebackType
from typing import Self

import pytest

from app.contexts.foundations.organization_structure.application.contracts import (
    CreateDepartmentCommand,
    SetSupervisorCommand,
)
from app.contexts.foundations.organization_structure.application.use_cases import (
    OrganizationStructureApplication,
)
from app.contexts.foundations.organization_structure.domain.models import DepartmentNode
from app.contexts.foundations.workforce.expert_management.contracts.roster import (
    DepartmentExpertCount,
    ExpertRosterSnapshot,
)
from app.contexts.shared_kernel import RuleViolation

NOW = datetime(2026, 7, 23, tzinfo=UTC)
ROOT_ID = uuid.UUID("71000000-0000-0000-0000-000000000001")
DEPT_ID = uuid.UUID("71000000-0000-0000-0000-000000000002")


def _root() -> DepartmentNode:
    return DepartmentNode(
        id=ROOT_ID,
        version="2026-07-23T00:00:00+00:00",
        name="公司",
        code="company",
        node_type="company",
        level=0,
        path=f"/{ROOT_ID}/",
        parent_id=None,
        supervisor_user_id=None,
        sort_order=0,
        create_time=NOW,
    )


class FakeRepository:
    def __init__(self) -> None:
        self.nodes = {ROOT_ID: _root()}

    async def get(self, department_id: uuid.UUID) -> DepartmentNode | None:
        return self.nodes.get(department_id)

    async def list_nodes(self) -> list[DepartmentNode]:
        return list(self.nodes.values())

    async def has_active_child(self, department_id: uuid.UUID) -> bool:
        return any(
            node.parent_id == department_id and not node.is_deleted
            for node in self.nodes.values()
        )

    async def add(self, department: DepartmentNode) -> None:
        self.nodes[department.id] = department

    async def save(self, department: DepartmentNode) -> None:
        self.nodes[department.id] = department


class FakeSourceChanges:
    def __init__(self) -> None:
        self.ids: list[uuid.UUID] = []

    async def publish_organization_changed(self, department_id: uuid.UUID) -> None:
        self.ids.append(department_id)


class FakeUnitOfWork:
    def __init__(self) -> None:
        self.departments = FakeRepository()
        self.source_changes = FakeSourceChanges()
        self.flush_count = 0
        self.commit_count = 0

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    async def flush(self) -> None:
        self.flush_count += 1

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        return None


class FakeExperts:
    def __init__(self) -> None:
        self.assignment = False

    async def list_department_roster(
        self, department_id: uuid.UUID
    ) -> tuple[ExpertRosterSnapshot, ...]:
        return ()

    async def count_by_department(
        self, *, include_personal: bool
    ) -> tuple[DepartmentExpertCount, ...]:
        return (DepartmentExpertCount(DEPT_ID, 2),)

    async def has_department_assignment(self, department_id: uuid.UUID) -> bool:
        return self.assignment


class FakeIdentities:
    def __init__(self) -> None:
        self.exists = True

    async def user_exists(self, user_id: uuid.UUID) -> bool:
        return self.exists


class FakeExternalDirectory:
    async def list_departments(self) -> tuple[object, ...]:
        return ()

    async def list_users(self, department_external_id: str) -> tuple[object, ...]:
        return ()


class FakeExternalIdentities:
    async def sync_user(self, user: object, *, department_id: uuid.UUID) -> bool:
        return False


class FakeDiscussions:
    def __init__(self) -> None:
        self.created: list[tuple[uuid.UUID, str]] = []

    async def create_department_channel(
        self, *, department_id: uuid.UUID, department_name: str
    ) -> None:
        self.created.append((department_id, department_name))


class FixedIdentifier:
    def new_id(self) -> uuid.UUID:
        return DEPT_ID


class FixedClock:
    def now(self) -> datetime:
        return NOW


def _application() -> tuple[
    OrganizationStructureApplication,
    FakeUnitOfWork,
    FakeExperts,
    FakeIdentities,
    FakeDiscussions,
]:
    uow = FakeUnitOfWork()
    experts = FakeExperts()
    identities = FakeIdentities()
    discussions = FakeDiscussions()
    application = OrganizationStructureApplication(
        uow_factory=lambda: uow,
        experts=experts,
        identities=identities,
        external_directory=FakeExternalDirectory(),
        external_identities=FakeExternalIdentities(),
        discussions=discussions,
        identifiers=FixedIdentifier(),
        clock=FixedClock(),
    )
    return application, uow, experts, identities, discussions


async def test_create_department_owns_channel_event_and_commit_boundary() -> None:
    application, uow, _, _, discussions = _application()

    created = await application.create_department(
        CreateDepartmentCommand(name="研发部", parent_id=ROOT_ID, code="rd")
    )

    assert created.department_id == DEPT_ID
    assert created.path == f"/{ROOT_ID}/{DEPT_ID}/"
    assert discussions.created == [(DEPT_ID, "研发部")]
    assert uow.source_changes.ids == [DEPT_ID]
    assert uow.flush_count == 1 and uow.commit_count == 1


async def test_snapshot_is_immutable_versioned_and_uses_expert_counts() -> None:
    application, uow, _, _, _ = _application()
    await application.create_department(
        CreateDepartmentCommand(name="研发部", parent_id=ROOT_ID, code="rd")
    )

    snapshot = await application.get_snapshot()

    assert snapshot.version
    assert snapshot.roots[0].children[0].employee_count == 2
    with pytest.raises(FrozenInstanceError):
        snapshot.version = "changed"  # type: ignore[misc]


async def test_ancestor_query_is_owned_by_organization() -> None:
    application, _, _, _, _ = _application()
    await application.create_department(
        CreateDepartmentCommand(name="研发部", parent_id=ROOT_ID, code="rd")
    )

    assert await application.ancestor_ids(DEPT_ID) == (ROOT_ID, DEPT_ID)
    assert await application.ancestor_ids(None) == ()


async def test_delete_rejects_assigned_experts_and_supervisor_must_exist() -> None:
    application, _, experts, identities, _ = _application()
    await application.create_department(
        CreateDepartmentCommand(name="研发部", parent_id=ROOT_ID, code="rd")
    )
    experts.assignment = True
    with pytest.raises(RuleViolation, match="智能体员工"):
        await application.delete_department(DEPT_ID)

    identities.exists = False
    with pytest.raises(RuleViolation, match="主管用户不存在"):
        await application.set_supervisor(
            SetSupervisorCommand(
                department_id=DEPT_ID,
                supervisor_user_id=uuid.uuid4(),
            )
        )
