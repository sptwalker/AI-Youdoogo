"""publish_release 用例测试（Module 2 / docs/23 §4.2）——纯 fake，离线。

覆盖：首次发布 v1；execution 改后再发布 v2 递增且不改 v1（不可变快照）；current 指针推进；
发布不存在/已删专家报错。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import TracebackType
from typing import Self

import pytest

from app.contexts.foundations.workforce.expert_management.application.use_cases import (
    ExpertManagementApplication,
)
from app.contexts.foundations.workforce.expert_management.contracts.roster import (
    DepartmentExpertCount,
    ExpertRosterSnapshot,
)
from app.contexts.foundations.workforce.expert_management.domain.models import (
    ExpertExecutionDefinition,
    ExpertProfile,
    ExpertRelease,
    OrgExpertMember,
)
from app.contexts.shared_kernel import ResourceNotFound

NOW = datetime(2026, 7, 31, tzinfo=UTC)
EXPERT_ID = uuid.UUID("73000000-0000-0000-0000-000000000001")


def _profile() -> ExpertProfile:
    return ExpertProfile(
        id=EXPERT_ID,
        version="v",
        create_time=NOW,
        member=OrgExpertMember(
            code="c",
            name="n",
            title="t",
            tier="member",
            department_id=None,
            report_to_id=None,
            owner_user_id=None,
            is_seed=False,
            is_active=True,
        ),
        execution=ExpertExecutionDefinition(
            prompt_template="v1 提示词",
            model_role="daily",
            permission_scope_json="{}",
            tools_json="[]",
            duty="d1",
        ),
    )


class FakeRepository:
    def __init__(self, profile: ExpertProfile | None) -> None:
        self.profile = profile

    async def get(self, expert_id: uuid.UUID) -> ExpertProfile | None:
        return self.profile if self.profile and self.profile.id == expert_id else None


class FakeReleases:
    def __init__(self) -> None:
        self.added: list[ExpertRelease] = []
        self.current: dict[uuid.UUID, uuid.UUID] = {}

    async def next_version_no(self, expert_id: uuid.UUID) -> int:
        return sum(1 for r in self.added if r.expert_id == expert_id) + 1

    async def add(self, release: ExpertRelease) -> None:
        self.added.append(release)

    async def set_current(self, expert_id: uuid.UUID, release_id: uuid.UUID) -> None:
        self.current[expert_id] = release_id


class FakeUnitOfWork:
    def __init__(self, profile: ExpertProfile | None) -> None:
        self.experts = FakeRepository(profile)
        self.releases = FakeReleases()
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
        return None

    async def commit(self) -> None:
        self.commit_count += 1


class SeqIdentifier:
    def __init__(self) -> None:
        self._n = 0

    def new_id(self) -> uuid.UUID:
        self._n += 1
        return uuid.UUID(int=self._n)


class FixedClock:
    def now(self) -> datetime:
        return NOW


class _NullRoster:
    async def get_roster_by_id(self, expert_id: uuid.UUID) -> ExpertRosterSnapshot | None:
        return None

    async def list_roster(
        self, *, include_personal: bool = False
    ) -> tuple[ExpertRosterSnapshot, ...]:
        return ()

    async def list_department_roster(
        self, department_id: uuid.UUID
    ) -> tuple[ExpertRosterSnapshot, ...]:
        return ()

    async def count_by_department(
        self, *, include_personal: bool
    ) -> tuple[DepartmentExpertCount, ...]:
        return ()


def _application(
    profile: ExpertProfile | None,
) -> tuple[ExpertManagementApplication, FakeUnitOfWork]:
    uow = FakeUnitOfWork(profile)
    app = ExpertManagementApplication(
        uow_factory=lambda: uow,
        roster=_NullRoster(),
        identifiers=SeqIdentifier(),
        clock=FixedClock(),
    )
    return app, uow


async def test_publish_cuts_v1_and_advances_current_pointer() -> None:
    profile = _profile()
    app, uow = _application(profile)
    operator = uuid.UUID(int=999)

    view = await app.publish_release(EXPERT_ID, released_by=operator)

    assert view.version_no == 1
    assert view.model_role == "daily"
    assert view.released_by == operator
    assert uow.releases.current[EXPERT_ID] == view.release_id
    assert uow.commit_count == 1


async def test_second_publish_increments_and_freezes_prior_snapshot() -> None:
    profile = _profile()
    app, uow = _application(profile)

    v1 = await app.publish_release(EXPERT_ID)
    # 编辑执行定义后再发布——v2 拿到新值，v1 快照恒等（不可变）
    profile.execution.prompt_template = "v2 提示词"
    profile.execution.model_role = "reasoning"
    v2 = await app.publish_release(EXPERT_ID)

    assert (v1.version_no, v2.version_no) == (1, 2)
    frozen_v1, frozen_v2 = uow.releases.added
    assert frozen_v1.prompt_template == "v1 提示词" and frozen_v1.model_role == "daily"
    assert frozen_v2.prompt_template == "v2 提示词" and frozen_v2.model_role == "reasoning"
    assert uow.releases.current[EXPERT_ID] == v2.release_id


async def test_publish_missing_expert_raises() -> None:
    app, _ = _application(None)
    with pytest.raises(ResourceNotFound):
        await app.publish_release(EXPERT_ID)


async def test_publish_deleted_expert_raises() -> None:
    profile = _profile()
    profile.delete()
    app, _ = _application(profile)
    with pytest.raises(ResourceNotFound):
        await app.publish_release(EXPERT_ID)
