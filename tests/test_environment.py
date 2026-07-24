"""环境快照与系统档案员单测（docs/13 §9，内存 SQLite，不发真实请求）。"""

import uuid
from collections.abc import AsyncGenerator
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.agents.base as base
import app.knowledge.ingest as ingest
import app.platform.outbox.source_change as source_change_events
from app.contexts.foundations.environment_projection import public as projection
from app.contexts.foundations.environment_projection.application.invalidation import (
    EnvironmentInvalidationState,
    InvalidateEnvironmentSnapshot,
)
from app.contexts.foundations.environment_projection.contracts.context_snapshot import (
    ContextSnapshot,
    MissingSnapshotSource,
    SnapshotScope,
)
from app.contexts.foundations.environment_projection.contracts.source_change import (
    ENVIRONMENT_SOURCE_CHANGED_V1,
    EnvironmentSourceChange,
)
from app.contexts.foundations.environment_projection.entrypoints import (
    operations as projection_operations,
)
from app.contexts.foundations.environment_projection.infrastructure import (
    source_change_handler,
)
from app.contexts.shared_kernel import ApplicationError
from app.models import Base
from app.models.agent import AgentRole
from app.models.knowledge import SCOPE_COMPANY, KnowledgeBase, KnowledgeFile
from app.models.system import COMPANY, DEPT_L1, SysDepartment, SysUser
from app.platform.outbox.model import OUTBOX_DONE, OutboxEvent
from app.services import (
    agent_role_service,
    data_source_service,
    org_service,
    workflow_worker,
)
from app.services import environment_service as legacy_environment

pytestmark = pytest.mark.usefixtures("_no_embed")


@pytest.fixture
def _no_embed(monkeypatch: pytest.MonkeyPatch) -> None:
    """embedding 打桩：不发真实请求。"""

    async def _fake_embed(texts: list[str]) -> list[list[float]]:
        return [[0.0] * 4 for _ in texts]

    monkeypatch.setattr(ingest, "embed_texts", _fake_embed)
    projection.invalidate_cache()
    source_change_handler.reset_invalidation_state()


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
        KnowledgeFile.file_name == projection.ENV_DOC_TITLE,
        KnowledgeFile.is_delete.is_(False),
    )
    return list((await db.execute(stmt)).scalars())


async def test_ensure_archivist_idempotent(db: AsyncSession) -> None:
    """档案员幂等创建，挂公司根。"""
    root, _, _ = await _seed_base(db)
    a1 = await projection.ensure_archivist(db)
    a2 = await projection.ensure_archivist(db)
    assert a1.id == a2.id
    assert a1.code == projection.ARCHIVIST_CODE and a1.is_seed
    assert a1.department_id == root.id
    events = list(
        (
            await db.execute(
                select(OutboxEvent).where(
                    OutboxEvent.event_type == ENVIRONMENT_SOURCE_CHANGED_V1
                )
            )
        ).scalars()
    )
    assert len(events) == 1
    assert events[0].aggregate_id == a1.id
    assert events[0].payload["event_id"] == str(events[0].id)


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
    snap1 = await projection.build_snapshot(db)
    snap2 = await projection.build_snapshot(db)
    assert snap1 == snap2  # 确定性
    for expected in ("平台运营部", "运营总监", "老板", "数数TD", "对接AI：运营总监"):
        assert expected in snap1
    assert "TD_SECRET" not in snap1 and "internal" not in snap1  # 敏感字段不进快照
    assert "password" not in snap1.lower()


async def test_context_snapshot_publishes_scope_versions_and_expiry(
    db: AsyncSession,
) -> None:
    """Canonical reads expose freshness and source evidence without ORM objects."""
    await _seed_base(db)
    agent = await agent_role_service.create_agent_role(
        db,
        name="快照元数据AI",
        prompt_template="x",
    )

    snapshot = await projection.get_context_snapshot(db)

    assert snapshot.scope == SnapshotScope(
        tenant_id="default",
        areas=("organization", "expert", "identity", "connector"),
    )
    assert snapshot.content
    assert not snapshot.stale
    assert snapshot.missing == ()
    assert snapshot.expires_at > snapshot.generated_at
    assert snapshot.is_usable(snapshot.generated_at)
    version = next(
        item
        for item in snapshot.source_versions
        if item.source_type == "expert" and item.source_id == agent.id
    )
    evidence = next(
        item
        for item in snapshot.provenance
        if item.source_type == "expert" and item.source_id == agent.id
    )
    assert version.version > 0
    assert evidence.event_id
    assert evidence.observed_at.tzinfo is not None
    assert await projection.get_env_context(db) == snapshot.content


async def test_context_snapshot_fails_closed_with_missing_source_metadata(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Projection failure is represented explicitly while the legacy text stays empty."""
    await _seed_base(db)

    async def _boom(_db: AsyncSession) -> str:
        raise RuntimeError("source unavailable")

    monkeypatch.setattr(projection_operations, "build_snapshot", _boom)
    snapshot = await projection.get_context_snapshot(db)

    assert snapshot.content == ""
    assert snapshot.stale
    assert {item.source_type for item in snapshot.missing} == set(snapshot.scope.areas)
    assert all(item.required for item in snapshot.missing)
    assert not snapshot.is_usable()
    assert await projection.get_env_context(db) == ""


async def test_legacy_facade_preserves_builder_monkeypatch_seam(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _seed_base(db)

    async def _legacy_snapshot(_db: AsyncSession) -> str:
        return "# legacy monkeypatch"

    monkeypatch.setattr(legacy_environment, "build_snapshot", _legacy_snapshot)
    snapshot = await legacy_environment.get_context_snapshot(db)

    assert snapshot.content == "# legacy monkeypatch"
    assert await legacy_environment.get_env_context(db) == snapshot.content


def test_context_snapshot_contract_is_immutable() -> None:
    now = datetime.now(UTC)
    snapshot = ContextSnapshot(
        scope=SnapshotScope(tenant_id="default", areas=("organization",)),
        content="snapshot",
        provenance=(),
        source_versions=(),
        missing=(
            MissingSnapshotSource(
                source_type="organization",
                reason="not_loaded",
                required=False,
            ),
        ),
        stale=False,
        generated_at=now,
        expires_at=now,
    )

    with pytest.raises(FrozenInstanceError):
        snapshot.stale = True  # type: ignore[misc]


async def test_refresh_env_doc_upsert_no_duplicate(db: AsyncSession) -> None:
    """连续刷新只保留一份《系统环境快照》。"""
    await _seed_base(db)
    await projection.refresh_env_doc(db)
    await projection.refresh_env_doc(db)
    files = await _env_files(db)
    assert len(files) == 1
    assert files[0].status == "indexed"


async def test_refresh_env_doc_nonfatal(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """ingest 失败/无 admin 都不抛，不连累业务操作。"""
    # 无 admin：直接跳过
    await projection.refresh_env_doc(db)
    assert await _env_files(db) == []
    # 有 admin 但 ingest 挂了：吞异常
    await _seed_base(db)

    async def _boom(*a: Any, **kw: Any) -> None:
        raise RuntimeError("embedding down")

    monkeypatch.setattr(legacy_environment.ingest, "ingest_text", _boom)
    await legacy_environment.refresh_env_doc(db)  # 不应抛


async def test_sources_publish_versioned_changes_without_sync_refresh(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """来源只写版本事件；不再同步反向调用 Environment Projection。"""
    root, _, _ = await _seed_base(db)
    calls: list[str] = []

    async def _spy(_db: AsyncSession) -> None:
        calls.append("refresh")

    monkeypatch.setattr(legacy_environment, "refresh_env_doc", _spy)
    await org_service.create_node(db, name="新部门", parent_id=root.id)
    await agent_role_service.create_agent_role(db, name="新AI", prompt_template="x")
    await data_source_service.create_ds(db, name="接口A", type="http_api")
    events = list(
        (
            await db.execute(
                select(OutboxEvent)
                .where(OutboxEvent.event_type == ENVIRONMENT_SOURCE_CHANGED_V1)
                .order_by(OutboxEvent.create_time)
            )
        ).scalars()
    )
    assert calls == []
    assert {event.payload["source_type"] for event in events} == {
        "organization",
        "expert",
        "connector",
    }
    for event in events:
        assert event.payload["event_id"] == str(event.id)
        assert event.payload["tenant_id"] == "default"
        assert event.payload["source_version"] > 0
        assert event.payload["occurred_at"]
        assert event.payload["scope"]


async def test_outbox_worker_is_the_single_snapshot_refresh_path(db: AsyncSession) -> None:
    """worker 消费来源事件后刷新文档并完成 Outbox。"""
    root, _, _ = await _seed_base(db)
    await org_service.create_node(db, name="事件驱动部门", parent_id=root.id)
    assert await workflow_worker.process_one(db, worker_id="environment-test")
    event = (
        await db.execute(
            select(OutboxEvent).where(
                OutboxEvent.event_type == ENVIRONMENT_SOURCE_CHANGED_V1
            )
        )
    ).scalar_one()
    await db.refresh(event)
    assert event.status == OUTBOX_DONE
    files = await _env_files(db)
    assert len(files) == 1
    assert files[0].status == "indexed"


def test_invalidation_ignores_duplicate_and_out_of_order_versions() -> None:
    """重复和乱序事件不回退 source version，也不重复失效。"""

    class CacheSpy:
        def __init__(self) -> None:
            self.calls = 0

        def invalidate(self) -> None:
            self.calls += 1

    cache = CacheSpy()
    use_case = InvalidateEnvironmentSnapshot(
        state=EnvironmentInvalidationState(),
        cache=cache,
    )
    source_id = uuid.uuid4()
    newest = EnvironmentSourceChange(
        event_id=uuid.uuid4(),
        event_type=ENVIRONMENT_SOURCE_CHANGED_V1,
        tenant_id="default",
        source_type="organization",
        source_id=source_id,
        source_version=2,
        occurred_at=datetime.now(UTC),
        affected_scopes=("organization",),
    )
    stale = EnvironmentSourceChange(
        event_id=uuid.uuid4(),
        event_type=ENVIRONMENT_SOURCE_CHANGED_V1,
        tenant_id="default",
        source_type="organization",
        source_id=source_id,
        source_version=1,
        occurred_at=datetime.now(UTC),
        affected_scopes=("organization",),
    )
    assert use_case.execute(newest).reason == "applied"
    assert use_case.execute(newest).reason == "duplicate"
    assert use_case.execute(stale).reason == "stale"
    assert cache.calls == 1


async def test_failed_projection_refresh_can_retry_same_event() -> None:
    """A failed refresh must not consume the only retryable source-change event."""

    class CacheSpy:
        def __init__(self) -> None:
            self.calls = 0

        def invalidate(self) -> None:
            self.calls += 1

    class RefreshSpy:
        def __init__(self) -> None:
            self.calls = 0

        async def refresh(self) -> None:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("projection unavailable")

    event_id = uuid.uuid4()
    event = OutboxEvent(
        id=event_id,
        aggregate_type="environment_source",
        aggregate_id=uuid.uuid4(),
        event_type=ENVIRONMENT_SOURCE_CHANGED_V1,
        dedupe_key=f"environment-retry:{event_id}",
        payload={
            "event_id": str(event_id),
            "event_type": ENVIRONMENT_SOURCE_CHANGED_V1,
            "tenant_id": "default",
            "source_type": "organization",
            "source_id": str(uuid.uuid4()),
            "source_version": 1,
            "occurred_at": datetime.now(UTC).isoformat(),
            "scope": ["organization"],
        },
    )
    cache = CacheSpy()
    refresh = RefreshSpy()

    with pytest.raises(RuntimeError, match="projection unavailable"):
        await source_change_handler.handle_source_change(
            event,
            cache=cache,
            refresh=refresh,
        )

    retried = await source_change_handler.handle_source_change(
        event,
        cache=cache,
        refresh=refresh,
    )
    assert retried.applied
    assert cache.calls == 2
    assert refresh.calls == 2


async def test_source_and_outbox_roll_back_together(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """事件无法记录时，来源事实不会独自提交。"""
    await _seed_base(db)

    async def _fail_publish(*args: object, **kwargs: object) -> OutboxEvent:
        raise RuntimeError("outbox unavailable")

    monkeypatch.setattr(source_change_events, "publish_source_change", _fail_publish)
    with pytest.raises(RuntimeError, match="outbox unavailable"):
        await data_source_service.create_ds(db, name="不可孤立提交", type="http_api")
    await db.rollback()
    assert await data_source_service.list_ds(db) == []


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
    projection.invalidate_cache()

    async def _boom(_db: AsyncSession) -> str:
        raise RuntimeError("db down")

    monkeypatch.setattr(projection_operations, "build_snapshot", _boom)
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
    with pytest.raises(ApplicationError, match="对接AI不存在"):
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
    snap = await projection.build_snapshot(db)
    n = (await db.execute(select(func.count()).select_from(AgentRole))).scalar_one()
    assert n == 3
    for i in range(3):
        assert f"AI{i}" in snap
