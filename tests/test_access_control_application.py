"""Access Control policies and grant use cases without ORM or frameworks."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import TracebackType
from typing import Self

import pytest

from app.contexts.foundations.access_control.application.contracts import (
    CreateGrantCommand,
)
from app.contexts.foundations.access_control.application.use_cases import (
    AccessControlApplication,
)
from app.contexts.foundations.access_control.contracts import (
    ResourceReadPolicyRequest,
    RolePolicyRequest,
    RowPolicyRequest,
)
from app.contexts.foundations.access_control.domain.models import (
    GranteeType,
    GrantTarget,
    PermissionLevel,
    ResourceGrantRecord,
)
from app.contexts.foundations.identity.contracts import Principal, PrincipalType
from app.contexts.shared_kernel import RuleViolation

NOW = datetime(2026, 7, 23, tzinfo=UTC)
USER_ID = uuid.UUID("30000000-0000-0000-0000-000000000001")
DEPARTMENT_ID = uuid.UUID("40000000-0000-0000-0000-000000000001")
PARENT_DEPARTMENT_ID = uuid.UUID("40000000-0000-0000-0000-000000000002")
GRANT_ID = uuid.UUID("50000000-0000-0000-0000-000000000001")
RESOURCE_ID = uuid.UUID("60000000-0000-0000-0000-000000000001")


def _principal(role: str = "member") -> Principal:
    return Principal(
        principal_type=PrincipalType.USER,
        principal_id=USER_ID,
        role_code=role,
        department_id=DEPARTMENT_ID,
    )


def _grant(
    *,
    grantee_type: GranteeType = GranteeType.USER,
    grantee_id: uuid.UUID = USER_ID,
    expires_at: datetime | None = None,
) -> ResourceGrantRecord:
    return ResourceGrantRecord(
        id=GRANT_ID,
        resource_type="knowledge_base",
        resource_id=RESOURCE_ID,
        grantee_type=grantee_type,
        grantee_id=grantee_id,
        permission=PermissionLevel.READ,
        granted_by=None,
        expires_at=expires_at,
        create_time=NOW,
    )


class FakeRepository:
    def __init__(self, records: list[ResourceGrantRecord] | None = None) -> None:
        self.records = records or []
        self.targets: tuple[GrantTarget, ...] = ()

    async def get(self, grant_id: uuid.UUID) -> ResourceGrantRecord | None:
        return next((record for record in self.records if record.id == grant_id), None)

    async def add(self, grant: ResourceGrantRecord) -> None:
        self.records.append(grant)

    async def save(self, grant: ResourceGrantRecord) -> None:
        return None

    async def list_records(
        self,
        *,
        resource_type: str | None,
        grantee_id: uuid.UUID | None,
    ) -> list[ResourceGrantRecord]:
        return [
            record
            for record in self.records
            if not record.is_deleted
            and (resource_type is None or record.resource_type == resource_type)
            and (grantee_id is None or record.grantee_id == grantee_id)
        ]

    async def find_for_targets(
        self,
        *,
        resource_type: str,
        targets: tuple[GrantTarget, ...],
    ) -> list[ResourceGrantRecord]:
        self.targets = targets
        return [
            record
            for record in self.records
            if record.resource_type == resource_type
            and GrantTarget(record.grantee_type, record.grantee_id) in targets
        ]


class FakeUnitOfWork:
    def __init__(self, repository: FakeRepository) -> None:
        self.grants = repository
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

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        return None


class FakeDepartments:
    async def ancestors_of(self, department_id: uuid.UUID | None) -> tuple[uuid.UUID, ...]:
        return (PARENT_DEPARTMENT_ID, DEPARTMENT_ID) if department_id else ()


class FakeKnowledgeVisibility:
    def __init__(self) -> None:
        self.extra_ids: tuple[uuid.UUID, ...] = ()

    async def visible_ids(
        self,
        *,
        department_id: uuid.UUID | None,
        is_admin: bool,
        extra_knowledge_ids: tuple[uuid.UUID, ...],
    ) -> tuple[uuid.UUID, ...]:
        self.extra_ids = extra_knowledge_ids
        return (uuid.UUID(int=99), *extra_knowledge_ids)


class FixedIdentifier:
    def new_id(self) -> uuid.UUID:
        return GRANT_ID


class FixedClock:
    def now(self) -> datetime:
        return NOW


def _application(
    records: list[ResourceGrantRecord] | None = None,
) -> tuple[AccessControlApplication, FakeUnitOfWork, FakeKnowledgeVisibility]:
    repository = FakeRepository(records)
    uow = FakeUnitOfWork(repository)
    knowledge = FakeKnowledgeVisibility()
    application = AccessControlApplication(
        uow_factory=lambda: uow,
        departments=FakeDepartments(),
        knowledge_visibility=knowledge,
        identifiers=FixedIdentifier(),
        clock=FixedClock(),
    )
    return application, uow, knowledge


def test_role_and_row_decisions_are_pure_and_conceal_hidden_resources() -> None:
    application, _, _ = _application()
    principal = _principal()

    denied_role = application.decide_role(
        RolePolicyRequest(principal=principal, allowed_roles=("admin",))
    )
    hidden_row = application.decide_row_visibility(
        RowPolicyRequest(principal=principal, creator_id=uuid.uuid4())
    )

    assert not denied_role.allowed and denied_role.reason == "无权限执行此操作"
    assert not hidden_row.allowed and hidden_row.conceal_resource
    assert hidden_row.reason == "资源不存在"


def test_privileged_row_scope_is_global_but_member_scope_is_explicit() -> None:
    application, _, _ = _application()

    assert application.row_visibility_scope(_principal("executive")).all_rows
    member_scope = application.row_visibility_scope(_principal())
    assert not member_scope.all_rows
    assert member_scope.creator_id == USER_ID
    assert member_scope.department_id == DEPARTMENT_ID
    assert member_scope.assignee_user_id == USER_ID


async def test_grants_include_user_and_department_ancestors_but_exclude_expired() -> None:
    active = _grant()
    expired = _grant(
        grantee_type=GranteeType.DEPARTMENT,
        grantee_id=PARENT_DEPARTMENT_ID,
        expires_at=NOW - timedelta(seconds=1),
    )
    expired.id = uuid.uuid4()
    expired.resource_id = uuid.uuid4()
    application, uow, _ = _application([active, expired])

    ids = await application.granted_resource_ids(_principal(), "knowledge_base")

    assert ids == (RESOURCE_ID,)
    assert GrantTarget(GranteeType.USER, USER_ID) in uow.grants.targets
    assert GrantTarget(GranteeType.DEPARTMENT, PARENT_DEPARTMENT_ID) in uow.grants.targets
    assert GrantTarget(GranteeType.DEPARTMENT, DEPARTMENT_ID) in uow.grants.targets


async def test_knowledge_visibility_unions_default_scope_with_explicit_grants() -> None:
    application, _, knowledge = _application([_grant()])

    ids = await application.visible_knowledge_ids(_principal())

    assert knowledge.extra_ids == (RESOURCE_ID,)
    assert set(ids) == {uuid.UUID(int=99), RESOURCE_ID}


async def test_admin_reads_every_resource_but_grant_does_not_confer_role_authority() -> None:
    application, _, _ = _application([_grant()])

    admin_read = await application.decide_resource_read(
        ResourceReadPolicyRequest(
            principal=_principal("admin"),
            resource_type="data_source",
            resource_id=uuid.uuid4(),
        )
    )
    member_admin_action = application.decide_role(
        RolePolicyRequest(principal=_principal(), allowed_roles=("admin",))
    )

    assert admin_read.allowed
    assert not member_admin_action.allowed


async def test_create_and_revoke_grant_each_commit_once() -> None:
    application, uow, _ = _application()
    created = await application.create_grant(
        CreateGrantCommand(
            resource_type="data_source",
            resource_id=RESOURCE_ID,
            grantee_type="user",
            grantee_id=USER_ID,
        )
    )
    await application.revoke_grant(created.id)

    assert created.id == GRANT_ID
    assert uow.grants.records[0].is_deleted
    assert uow.commit_count == 2


async def test_create_rejects_unsupported_resource_type_before_transaction() -> None:
    application, uow, _ = _application()

    with pytest.raises(RuleViolation, match="resource_type 仅支持"):
        await application.create_grant(
            CreateGrantCommand(
                resource_type="workflow",
                resource_id=RESOURCE_ID,
                grantee_type="user",
                grantee_id=USER_ID,
            )
        )

    assert uow.grants.records == []
    assert uow.commit_count == 0
