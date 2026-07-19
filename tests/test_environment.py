"""环境快照与系统档案员单测（docs/13 §9，内存 SQLite，不发真实请求）。"""

import uuid
from collections.abc import AsyncGenerator
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.agents import base
from app.core.exceptions import AppError
from app.knowledge import ingest
from app.models import Base
from app.models.agent import AgentRole
from app.models.knowledge import SCOPE_COMPANY, KnowledgeBase, KnowledgeFile
from app.models.system import COMPANY, DEPT_L1, SysDepartment, SysUser
from app.services import (
    agent_role_service,
    data_source_service,
    org_service,
)
from app.services import (
    environment_service as svc,
)

pytestmark = pytest.mark.usefixtures("_no_embed")


@pytest.fixture
def _no_embed(monkeypatch: pytest.MonkeyPatch) -> None:
    """embedding 打桩：不发真实请求。"""

    async def _fake_embed(texts: list[str]) -> list[list[float]]:
        return [[0.0] * 4 for _ in texts]

    monkeypatch.setattr(ingest, "embed_texts", _fake_embed)
    svc._cache = None  # 各测试互不串缓存


@pytest.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


async def _seed_base(db: AsyncSession) -> tuple[SysDepartment, SysUser, KnowledgeBase]:
    """公司根 + admin 用户 + 默认公司库。"""
    root = SysDepartment(name="创想悦动", code="company", node_type=COMPANY, level=0, path="")
    admin = SysUser(username="boss", password_hash="x", real_name="老板", role_code="admin")
    kb = KnowledgeBase(name="公司公共知识库", code="kb_default", scope=SCOPE_COMPANY,
                       is_default=True)
    db.add_all([root, admin, kb])
    await db.commit()
    root.path = f"/{root.id}/"
    await db.commit()
    return root, admin, kb


async def _env_files(db: AsyncSession) -> list[KnowledgeFile]:
    stmt = select(KnowledgeFile).where(
        KnowledgeFile.file_name == svc.ENV_DOC_TITLE, KnowledgeFile.is_delete.is_(False)
    )
    return list((await db.execute(stmt)).scalars())


async def test_ensure_archivist_idempotent(db: AsyncSession) -> None:
    """档案员幂等创建，挂公司根。"""
    root, _, _ = await _seed_base(db)
    a1 = await svc.ensure_archivist(db)
    a2 = await svc.ensure_archivist(db)
    assert a1.id == a2.id
    assert a1.code == svc.ARCHIVIST_CODE and a1.is_seed
    assert a1.department_id == root.id


async def test_build_snapshot_content_and_determinism(db: AsyncSession) -> None:
    """快照含部门/AI/用户/数据源与对接AI；不含敏感字段；两次调用字节相等。"""
    root, _, _ = await _seed_base(db)
    dept = SysDepartment(name="平台运营部", code="ops", parent_id=root.id,
                         node_type=DEPT_L1, level=1, path="")
    db.add(dept)
    await db.commit()
    agent = await agent_role_service.create_agent_role(
        db, name="运营总监", prompt_template="x", department_id=dept.id, title="总监"
    )
    await data_source_service.create_ds(
        db, name="数数TD", type="thinkingdata", secret_ref="TD_SECRET",
        config={"host": "internal"}, owner_agent_id=agent.id,
    )
    snap1 = await svc.build_snapshot(db)
    snap2 = await svc.build_snapshot(db)
    assert snap1 == snap2  # 确定性
    for expected in ("平台运营部", "运营总监", "老板", "数数TD", "对接AI：运营总监"):
        assert expected in snap1
    assert "TD_SECRET" not in snap1 and "internal" not in snap1  # 敏感字段不进快照
    assert "password" not in snap1.lower()


async def test_refresh_env_doc_upsert_no_duplicate(db: AsyncSession) -> None:
    """连续刷新只保留一份《系统环境快照》。"""
    await _seed_base(db)
    await svc.refresh_env_doc(db)
    await svc.refresh_env_doc(db)
    files = await _env_files(db)
    assert len(files) == 1
    assert files[0].status == "indexed"


async def test_refresh_env_doc_nonfatal(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """ingest 失败/无 admin 都不抛，不连累业务操作。"""
    # 无 admin：直接跳过
    await svc.refresh_env_doc(db)
    assert await _env_files(db) == []
    # 有 admin 但 ingest 挂了：吞异常
    await _seed_base(db)

    async def _boom(*a: Any, **kw: Any) -> None:
        raise RuntimeError("embedding down")

    monkeypatch.setattr(svc.ingest, "ingest_text", _boom)
    await svc.refresh_env_doc(db)  # 不应抛


async def test_triggers_call_refresh(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """组织/AI/数据源变更后触发快照刷新。"""
    root, _, _ = await _seed_base(db)
    calls: list[str] = []

    async def _spy(_db: AsyncSession) -> None:
        calls.append("refresh")

    monkeypatch.setattr(svc, "refresh_env_doc", _spy)
    await org_service.create_node(db, name="新部门", parent_id=root.id)
    await agent_role_service.create_agent_role(db, name="新AI", prompt_template="x")
    await data_source_service.create_ds(db, name="接口A", type="http_api")
    assert len(calls) == 3


async def test_env_context_injection_flag(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """注入开关：开→system prompt 含快照；关→不含；构建失败→不阻断。"""
    root, _, _ = await _seed_base(db)
    agent = await agent_role_service.create_agent_role(
        db, name="助理甲", prompt_template="你是助理。"
    )

    _, system_on, _, _ = await base._prepare(db, agent, "hi", use_knowledge=False)
    assert "【系统环境快照】" in system_on and "助理甲" in system_on

    async def _off(_db: AsyncSession, key: str, default: Any) -> Any:
        return False if key == "agent_env_context" else default

    monkeypatch.setattr(base.config_service, "resolve", _off)
    _, system_off, _, _ = await base._prepare(db, agent, "hi", use_knowledge=False)
    assert "【系统环境快照】" not in system_off

    monkeypatch.undo()
    svc._cache = None

    async def _boom(_db: AsyncSession) -> str:
        raise RuntimeError("db down")

    monkeypatch.setattr(svc, "build_snapshot", _boom)
    _, system_fail, _, _ = await base._prepare(db, agent, "hi", use_knowledge=False)
    assert "【系统环境快照】" not in system_fail  # 失败静默跳过，不抛


async def test_ds_owner_agent_roundtrip(db: AsyncSession) -> None:
    """数据源对接AI：创建/更新往返；指派不存在的 AI 报 404。"""
    await _seed_base(db)
    a = await agent_role_service.create_agent_role(db, name="数据AI", prompt_template="x")
    ds = await data_source_service.create_ds(db, name="接口B", type="http_api", owner_agent_id=a.id)
    assert ds.owner_agent_id == a.id
    listed = await data_source_service.list_ds(db)
    assert listed[0]["owner_agent_name"] == "数据AI"
    b = await agent_role_service.create_agent_role(db, name="数据AI2", prompt_template="x")
    ds = await data_source_service.update_ds(db, ds.id, owner_agent_id=b.id)
    assert ds.owner_agent_id == b.id
    with pytest.raises(AppError, match="对接AI不存在"):
        await data_source_service.create_ds(
            db, name="接口C", type="http_api", owner_agent_id=uuid.uuid4()
        )
    # 环境文档确随变更累积刷新且不重复
    files = await _env_files(db)
    assert len(files) <= 1


async def test_snapshot_counts_match(db: AsyncSession) -> None:
    """快照 AI 花名册与 agent_role 表一致（排除专属助理由 list_agent_roles 保证）。"""
    await _seed_base(db)
    for i in range(3):
        await agent_role_service.create_agent_role(db, name=f"AI{i}", prompt_template="x")
    snap = await svc.build_snapshot(db)
    n = (await db.execute(select(func.count()).select_from(AgentRole))).scalar_one()
    assert n == 3
    for i in range(3):
        assert f"AI{i}" in snap
