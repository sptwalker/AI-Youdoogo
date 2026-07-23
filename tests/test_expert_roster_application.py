"""Expert lifecycle application tests using only pure profile and roster contracts."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import TracebackType
from typing import Self

import pytest

from app.contexts.foundations.workforce.expert_management.application.contracts import (
    CreateExpertCommand,
    SeedExpertCommand,
    UpdateExpertCommand,
)
from app.contexts.foundations.workforce.expert_management.application.errors import (
    ExpertWriteConflict,
)
from app.contexts.foundations.workforce.expert_management.application.use_cases import (
    ExpertManagementApplication,
)
from app.contexts.foundations.workforce.expert_management.contracts.roster import (
    DepartmentExpertCount,
    ExpertRosterSnapshot,
)
from app.contexts.foundations.workforce.expert_management.domain.models import ExpertProfile
from app.contexts.shared_kernel import ConflictDetected

NOW = datetime(2026, 7, 23, tzinfo=UTC)
EXPERT_ID = uuid.UUID("72000000-0000-0000-0000-000000000001")
DEPT_ID = uuid.UUID("72000000-0000-0000-0000-000000000002")


def _snapshot(profile: ExpertProfile) -> ExpertRosterSnapshot:
    return ExpertRosterSnapshot(
        expert_id=profile.id,
        version=profile.version,
        code=profile.code,
        name=profile.name,
        title=profile.title,
        tier=profile.tier,
        department_id=profile.department_id,
        report_to_id=profile.report_to_id,
        owner_user_id=profile.owner_user_id,
        duty=profile.duty,
        prompt_template=profile.prompt_template,
        model_role=profile.model_role,
        permission_scope_json=profile.permission_scope_json,
        tools_json=profile.tools_json,
        is_seed=profile.is_seed,
        is_active=profile.is_active,
        create_time=profile.create_time,
    )


class FakeRepository:
    def __init__(self) -> None:
        self.profile: ExpertProfile | None = None

    async def get(self, expert_id: uuid.UUID) -> ExpertProfile | None:
        return self.profile if self.profile and self.profile.id == expert_id else None

    async def get_by_code(self, code: str) -> ExpertProfile | None:
        return self.profile if self.profile and self.profile.code == code else None

    async def get_by_name(self, name: str) -> ExpertProfile | None:
        return self.profile if self.profile and self.profile.name == name else None

    async def add(self, expert: ExpertProfile) -> None:
        self.profile = expert

    async def save(self, expert: ExpertProfile) -> None:
        self.profile = expert


class FakeSources:
    def __init__(self) -> None:
        self.ids: list[uuid.UUID] = []

    async def publish_expert_changed(self, expert_id: uuid.UUID) -> None:
        self.ids.append(expert_id)


class FakeUnitOfWork:
    def __init__(self) -> None:
        self.experts = FakeRepository()
        self.source_changes = FakeSources()
        self.flush_error: Exception | None = None
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
        if self.flush_error:
            raise self.flush_error

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        return None


class FakeRoster:
    def __init__(self, repository: FakeRepository) -> None:
        self._repository = repository

    async def get_roster_by_id(
        self, expert_id: uuid.UUID
    ) -> ExpertRosterSnapshot | None:
        profile = await self._repository.get(expert_id)
        return _snapshot(profile) if profile else None

    async def list_roster(
        self, *, include_personal: bool = False
    ) -> tuple[ExpertRosterSnapshot, ...]:
        profile = self._repository.profile
        return (_snapshot(profile),) if profile else ()

    async def list_department_roster(
        self, department_id: uuid.UUID
    ) -> tuple[ExpertRosterSnapshot, ...]:
        return await self.list_roster()

    async def count_by_department(
        self, *, include_personal: bool
    ) -> tuple[DepartmentExpertCount, ...]:
        return ()


class FixedIdentifier:
    def new_id(self) -> uuid.UUID:
        return EXPERT_ID


class FixedClock:
    def now(self) -> datetime:
        return NOW


def _application() -> tuple[ExpertManagementApplication, FakeUnitOfWork]:
    uow = FakeUnitOfWork()
    return (
        ExpertManagementApplication(
            uow_factory=lambda: uow,
            roster=FakeRoster(uow.experts),
            identifiers=FixedIdentifier(),
            clock=FixedClock(),
        ),
        uow,
    )


async def test_create_preserves_json_snapshot_and_publishes_before_commit() -> None:
    application, uow = _application()

    created = await application.create(
        CreateExpertCommand(
            name="数据专家",
            prompt_template="仅分析授权数据",
            department_id=DEPT_ID,
            permission_scope_json='{"depth":2}',
            tools_json='["search",{"key":"query"}]',
        )
    )

    assert created.expert_id == EXPERT_ID
    assert created.permission_scope_json == '{"depth":2}'
    assert created.tools_json == '["search",{"key":"query"}]'
    assert uow.source_changes.ids == [EXPERT_ID]
    assert uow.commit_count == 1


async def test_create_preserves_personal_assistant_owner() -> None:
    application, _ = _application()
    owner_user_id = uuid.UUID(int=77)

    created = await application.create(
        CreateExpertCommand(
            name="个人助理",
            prompt_template="协助本人工作",
            owner_user_id=owner_user_id,
        )
    )

    assert created.owner_user_id == owner_user_id


async def test_partial_update_keeps_prompt_and_assignments() -> None:
    application, uow = _application()
    await application.create(
        CreateExpertCommand(
            name="经营专家",
            prompt_template="保留提示词",
            department_id=DEPT_ID,
            report_to_id=uuid.UUID(int=88),
        )
    )

    updated = await application.update(
        UpdateExpertCommand(
            expert_id=EXPERT_ID,
            prompt_template="",
            department_id=None,
            report_to_id=None,
        )
    )

    assert updated.prompt_template == "保留提示词"
    assert updated.department_id == DEPT_ID
    assert updated.report_to_id == uuid.UUID(int=88)
    assert uow.commit_count == 2


async def test_seed_is_idempotent_and_preserves_existing_prompt() -> None:
    application, uow = _application()
    command = SeedExpertCommand(
        code="exec_cfo",
        name="首席财务顾问（CFO）",
        prompt_template="模板提示词",
        title="CFO",
        tier="exec",
        model_role="reasoning",
        department_id=DEPT_ID,
        duty="CFO",
    )

    created = await application.seed(command)
    assert created.code == "exec_cfo" and created.is_seed is True
    assert created.prompt_template == "模板提示词"

    assert uow.experts.profile is not None
    uow.experts.profile.prompt_template = "管理员自定义提示词"
    updated = await application.seed(command)

    assert updated.expert_id == created.expert_id
    assert updated.prompt_template == "管理员自定义提示词"
    assert uow.commit_count == 2
    assert uow.source_changes.ids == [EXPERT_ID]


async def test_create_translates_unique_conflict_without_publishing() -> None:
    application, uow = _application()
    uow.flush_error = ExpertWriteConflict()

    with pytest.raises(ConflictDetected, match="角色名或编码已存在"):
        await application.create(
            CreateExpertCommand(name="重复专家", prompt_template="x")
        )

    assert uow.source_changes.ids == []
    assert uow.commit_count == 0
