"""engine 溯源戳 + 创建期固定 + drain 只读闸闭环回归（docs/24 §4 / §8）。

覆盖：①创建 run 读 config.workflow_engine 盖戳 ②config 事后翻转不改写已存在 run（pin 不变式）、
新 run 盖新值 ③count_active_runs_by_engine 计非终态、终态后不计 ④get_workflow_engine 配置驱动 +
未知名 fail-closed。tmp sqlite（真跑 create_workflow），不碰共享 youdoo 库。
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.agents.workflow_engine import get_workflow_engine
from app.contexts.foundations.execution.workflow_runtime.infrastructure import (
    sqlalchemy_repository,
)
from app.core.config import get_settings
from app.models import Base
from app.models.agent import AgentRole
from app.models.system import SysUser
from app.models.workflow import RUN_SUCCEEDED
from app.services import workflow_service
from app.services.orchestration_service import PlanStep, is_red_line


@pytest.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
    await engine.dispose()


def _steps() -> list[PlanStep]:
    # 持久化编排要求 ≥2 步（否则 RuleViolation）。
    return [
        PlanStep(no=0, title="第一步", skill="data_query", instruction="q", depends_on=[]),
        PlanStep(no=1, title="第二步", skill="deliver", instruction="d", depends_on=[0]),
    ]


async def _create_run(db: AsyncSession) -> uuid.UUID:
    user = SysUser(username=f"u-{uuid.uuid4().hex[:8]}", password_hash="x", role_code="admin")
    role = AgentRole(
        name=f"a-{uuid.uuid4().hex[:8]}",
        prompt_template="仅测试",
        model_role="daily",
        tools=["none"],
    )
    db.add_all([user, role])
    await db.commit()
    run = await workflow_service.create_workflow(
        db,
        request="先执行第一步再执行第二步",
        title="engine-stamp",
        creator_id=user.id,
        assignee_agent_id=role.id,
        steps=_steps(),
        is_red_line=is_red_line,
    )
    await db.commit()
    return run.id


async def test_engine_stamped_at_creation_and_pinned(db: AsyncSession) -> None:
    """创建期读 config 盖戳；config 事后翻转不改写已存在 run（pin），新 run 才盖新值。"""
    s = get_settings()
    saved = s.workflow_engine
    try:
        run_a = await _create_run(db)  # 默认 database
        a = await sqlalchemy_repository.get_run(db, run_a)
        assert a.engine == "database"  # 读默认 config 盖戳

        s.workflow_engine = "remote"  # 事后翻转配置（仅影响新建；戳路径不校验 _ENGINES）
        run_b = await _create_run(db)
        b = await sqlalchemy_repository.get_run(db, run_b)
        assert b.engine == "remote"  # 新 run 创建期读新 config 盖新值

        a2 = await sqlalchemy_repository.get_run(db, run_a)
        assert a2.engine == "database"  # pin：已存在 run 不被改写 → 无双真源
    finally:
        s.workflow_engine = saved


async def test_drain_counts_active_by_engine_excludes_terminal(db: AsyncSession) -> None:
    """drain 闸计非终态 run；转终态后排空。"""
    run_id = await _create_run(db)
    assert await sqlalchemy_repository.count_active_runs_by_engine(db) == {"database": 1}

    run = await sqlalchemy_repository.get_run(db, run_id)
    run.status = RUN_SUCCEEDED  # 转终态
    await db.commit()
    assert await sqlalchemy_repository.count_active_runs_by_engine(db) == {}  # 已排空


def test_get_workflow_engine_config_driven_fail_closed() -> None:
    """缺省读 config.workflow_engine 选引擎；未知名拒绝（fail-closed），不静默回落。"""
    s = get_settings()
    saved = s.workflow_engine
    try:
        s.workflow_engine = "database"
        assert get_workflow_engine() is get_workflow_engine("database")  # 同一单例
        with pytest.raises(ValueError):
            get_workflow_engine("nope")  # 未知引擎名 → 拒绝
    finally:
        s.workflow_engine = saved
