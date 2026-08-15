"""Project Management 应用层单测（离线，Fake 仓储/UoW，无 DB）。

覆盖：领域归档/编辑不变量、创建落库 + commit、行级隔离（他人项目当作不存在）、更新、归档后不可编辑。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.contexts.business.project_management.application.contracts import (
    CreateProjectCommand,
    ListProjectsQuery,
    UpdateProjectCommand,
)
from app.contexts.business.project_management.application.use_cases import (
    ProjectApplication,
)
from app.contexts.business.project_management.domain.models import (
    ACTIVE,
    ARCHIVED,
    Project,
)
from app.contexts.shared_kernel import ResourceNotFound, RuleViolation

_OWNER = uuid.UUID("11111111-1111-1111-1111-111111111111")
_OTHER = uuid.UUID("22222222-2222-2222-2222-222222222222")


class _FakeRepository:
    def __init__(self) -> None:
        self._rows: dict[uuid.UUID, Project] = {}

    async def add(self, project: Project) -> None:
        self._rows[project.id] = project

    async def get(self, project_id: uuid.UUID) -> Project | None:
        return self._rows.get(project_id)

    async def save(self, project: Project) -> None:
        self._rows[project.id] = project

    async def list_for_owner(
        self, *, owner_id: uuid.UUID, status: str | None, limit: int
    ) -> tuple[Project, ...]:
        rows = [
            p
            for p in self._rows.values()
            if p.owner_id == owner_id and (status is None or p.status == status)
        ]
        return tuple(rows[:limit])


class _FakeUnitOfWork:
    def __init__(self, repo: _FakeRepository) -> None:
        self.projects = repo
        self.commits = 0
        self.rollbacks = 0

    async def __aenter__(self) -> _FakeUnitOfWork:
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        if exc_type is not None:
            self.rollbacks += 1

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


class _StaticClock:
    def __init__(self, moment: datetime) -> None:
        self._moment = moment

    def now(self) -> datetime:
        return self._moment


class _SequenceIdentifiers:
    def __init__(self) -> None:
        self._n = 0

    def new_id(self) -> uuid.UUID:
        self._n += 1
        return uuid.UUID(int=self._n)


def _application() -> tuple[ProjectApplication, list[_FakeUnitOfWork]]:
    repo = _FakeRepository()
    units: list[_FakeUnitOfWork] = []

    def _factory() -> _FakeUnitOfWork:
        unit = _FakeUnitOfWork(repo)
        units.append(unit)
        return unit

    app = ProjectApplication(
        uow_factory=_factory,
        clock=_StaticClock(datetime(2026, 8, 14, tzinfo=UTC)),
        identifiers=_SequenceIdentifiers(),
    )
    return app, units


# ── 领域不变量 ───────────────────────────────────────────
def test_create_rejects_blank_name() -> None:
    with pytest.raises(RuleViolation):
        Project.create(
            project_id=uuid.uuid4(),
            owner_id=_OWNER,
            name="   ",
            description=None,
            department_id=None,
            created_at=datetime(2026, 8, 14, tzinfo=UTC),
        )


def test_archived_project_is_not_editable() -> None:
    project = Project.create(
        project_id=uuid.uuid4(),
        owner_id=_OWNER,
        name="研发",
        description=None,
        department_id=None,
        created_at=datetime(2026, 8, 14, tzinfo=UTC),
    )
    project.archive(at=datetime(2026, 8, 14, tzinfo=UTC))
    assert project.status == ARCHIVED
    with pytest.raises(RuleViolation):
        project.rename("改名")


# ── 应用用例 ─────────────────────────────────────────────
async def test_create_persists_and_commits() -> None:
    app, units = _application()
    result = await app.create(CreateProjectCommand(owner_id=_OWNER, name="冬季营销"))
    assert result.status == ACTIVE and result.owner_id == _OWNER
    assert [unit.commits for unit in units] == [1]


async def test_get_isolates_by_owner() -> None:
    app, _ = _application()
    created = await app.create(CreateProjectCommand(owner_id=_OWNER, name="私有项目"))
    # 他人访问 → 当作不存在（不泄露存在性）
    with pytest.raises(ResourceNotFound):
        await app.get(created.id, owner_id=_OTHER)
    got = await app.get(created.id, owner_id=_OWNER)
    assert got.id == created.id


async def test_list_only_returns_own_projects() -> None:
    app, _ = _application()
    await app.create(CreateProjectCommand(owner_id=_OWNER, name="我的"))
    await app.create(CreateProjectCommand(owner_id=_OTHER, name="他的"))
    mine = await app.list(ListProjectsQuery(owner_id=_OWNER))
    assert [p.name for p in mine] == ["我的"]


async def test_update_renames() -> None:
    app, _ = _application()
    created = await app.create(CreateProjectCommand(owner_id=_OWNER, name="旧名"))
    updated = await app.update(
        UpdateProjectCommand(project_id=created.id, owner_id=_OWNER, name="新名")
    )
    assert updated.name == "新名"


async def test_archive_then_update_rejected() -> None:
    app, _ = _application()
    created = await app.create(CreateProjectCommand(owner_id=_OWNER, name="待归档"))
    archived = await app.archive(created.id, owner_id=_OWNER)
    assert archived.status == ARCHIVED and archived.archived_at is not None
    with pytest.raises(RuleViolation):
        await app.update(
            UpdateProjectCommand(project_id=created.id, owner_id=_OWNER, name="改")
        )
