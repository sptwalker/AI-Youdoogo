"""工作流模板管理面单测（docs/25 P5-1）：纯校验（环/悬挂/自依赖/未知 skill）、repo 往返、
应用守卫（种子拒删 / 取不到 ResourceNotFound）。全程 sqlite，不触共享 PG。
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.contexts.foundations.execution.workflow_templating import public as management
from app.contexts.foundations.execution.workflow_templating.application.validation import (
    validate_template_steps,
)
from app.contexts.foundations.execution.workflow_templating.contracts import (
    CreateTemplateCommand,
    TemplateStep,
    UpdateTemplateCommand,
)
from app.contexts.foundations.execution.workflow_templating.infrastructure import repository
from app.contexts.shared_kernel import InvalidInput, ResourceNotFound, RuleViolation
from app.models import Base
from app.models.workflow_template import WorkflowTemplate

_SKILLS = frozenset({"data_query", "deliver"})


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        yield db
    await engine.dispose()


def _step(no: int, skill: str = "data_query", depends: tuple[int, ...] = ()) -> TemplateStep:
    return TemplateStep(no, f"步骤{no}", skill, "指令", depends, None)


# ── 纯校验 ────────────────────────────────────────────────
def test_validate_accepts_valid_dag() -> None:
    steps = (_step(0), _step(1), _step(2, "deliver", (0, 1)))
    validate_template_steps(steps, _SKILLS)  # 不抛即通过


def test_validate_rejects_empty() -> None:
    with pytest.raises(InvalidInput):
        validate_template_steps((), _SKILLS)


def test_validate_rejects_unknown_skill() -> None:
    with pytest.raises(InvalidInput):
        validate_template_steps((_step(0, "no_such_skill"),), _SKILLS)


def test_validate_rejects_duplicate_no() -> None:
    with pytest.raises(InvalidInput):
        validate_template_steps((_step(0), _step(0)), _SKILLS)


def test_validate_rejects_dangling_dep() -> None:
    with pytest.raises(InvalidInput):
        validate_template_steps((_step(0, depends=(9,)),), _SKILLS)


def test_validate_rejects_self_dep() -> None:
    with pytest.raises(InvalidInput):
        validate_template_steps((_step(0, depends=(0,)),), _SKILLS)


def test_validate_rejects_cycle() -> None:
    # 0→1→2→0 成环（每步依赖前一步、最后一步又依赖首步）
    steps = (_step(0, depends=(2,)), _step(1, depends=(0,)), _step(2, depends=(1,)))
    with pytest.raises(InvalidInput):
        validate_template_steps(steps, _SKILLS)


# ── repo 往返（单写者）────────────────────────────────────
async def test_repo_crud_roundtrip(session: AsyncSession) -> None:
    new_id = await repository.create(
        session,
        CreateTemplateCommand(
            name="模板A", description="d", department_id=None,
            steps=(_step(0), _step(1, "deliver", (0,))),
        ),
    )
    await session.commit()

    view = await repository.get_any(session, new_id)
    assert view is not None
    assert view.name == "模板A"
    assert view.enabled is True
    assert view.is_seed is False
    assert [s.no for s in view.steps] == [0, 1]
    assert view.steps[1].depends_on == (0,)

    await repository.update(
        session, new_id, UpdateTemplateCommand(name="模板A2", enabled=False)
    )
    await session.commit()
    updated = await repository.get_any(session, new_id)
    assert updated is not None
    assert updated.name == "模板A2"
    assert updated.enabled is False  # 停用仍在 get_any 可见

    assert [v.name for v in await repository.list_all(session)] == ["模板A2"]

    await repository.soft_delete(session, new_id)
    await session.commit()
    assert await repository.get_any(session, new_id) is None  # 软删不可见
    assert await repository.list_all(session) == []


async def test_repo_list_all_filters_department(session: AsyncSession) -> None:
    dept = uuid.uuid4()
    await repository.create(
        session,
        CreateTemplateCommand(name="部门模板", description=None, department_id=dept,
                              steps=(_step(0),)),
    )
    await repository.create(
        session,
        CreateTemplateCommand(name="公司模板", description=None, department_id=None,
                              steps=(_step(0),)),
    )
    await session.commit()
    assert [v.name for v in await repository.list_all(session, dept)] == ["部门模板"]


# ── 应用守卫 ──────────────────────────────────────────────
async def test_delete_seed_rejected(session: AsyncSession) -> None:
    seed = WorkflowTemplate(name="种子", steps=[], is_seed=True)
    session.add(seed)
    await session.commit()
    with pytest.raises(RuleViolation):
        await management.delete_template(session, seed.id)


async def test_get_missing_raises_not_found(session: AsyncSession) -> None:
    with pytest.raises(ResourceNotFound):
        await management.get_template(session, uuid.uuid4())


async def test_delete_missing_raises_not_found(session: AsyncSession) -> None:
    with pytest.raises(ResourceNotFound):
        await management.delete_template(session, uuid.uuid4())


async def test_create_via_management_validates_skill(session: AsyncSession) -> None:
    # 走真实能力白名单：坏 skill 被拦（不触 DB 写）
    with pytest.raises(InvalidInput):
        await management.create_template(
            session,
            CreateTemplateCommand(name="坏", description=None, department_id=None,
                                  steps=(_step(0, "no_such_skill"),)),
        )
    assert await repository.list_all(session) == []


async def test_create_and_update_via_management(session: AsyncSession) -> None:
    # data_query/deliver 属真实注册能力，管理层端到端通
    view = await management.create_template(
        session,
        CreateTemplateCommand(name="月报副本", description=None, department_id=None,
                              steps=(_step(0), _step(1, "deliver", (0,)))),
    )
    assert view.name == "月报副本"
    updated = await management.update_template(
        session, view.id, UpdateTemplateCommand(enabled=False)
    )
    assert updated.enabled is False


async def test_create_rejects_unknown_department(session: AsyncSession) -> None:
    # 坏归属 FK 在写入前被 get_node 拦成 ResourceNotFound（否则 commit 抛 IntegrityError→500）
    with pytest.raises(ResourceNotFound):
        await management.create_template(
            session,
            CreateTemplateCommand(name="坏归属", description=None,
                                  department_id=uuid.uuid4(), steps=(_step(0),)),
        )
    assert await repository.list_all(session) == []  # 未落库


# ── HTTP DTO 约束（PATCH 与 POST 名称一致非空）────────────────────
def test_update_dto_rejects_blank_name() -> None:
    from pydantic import ValidationError

    from app.api.v1.workflow_templates import TemplateUpdate

    for bad in ("", "   "):
        with pytest.raises(ValidationError):
            TemplateUpdate(name=bad)
    assert TemplateUpdate().name is None  # 不传 name = 不改（合法）
