"""Module 3 后台步骤异步远端执行（docs/23 §6.3 第二场景）离线回归。

覆盖：出站分叉（命中 allowlist→停车+step.ready；不命中→execute 逐字不变）、停车不被 ready_steps
重选、回发唤醒+advance、双层幂等（同 completed 二次→finalize False、无第二 advance）、red_line
唤醒→WAITING_HUMAN 且无 advance、超时兜底（租约 0→expired→本地 execute 降级）、StepReadyRelay
投递期注入新鲜 callback_token（OutboxEvent 行 payload **不含**）、completed 经 http inbox 投影唤醒。

harness：tmp sqlite（真跑 finalize/complete_step 唯一 writer）+ 进程 Settings 单例临时改开关。
不碰共享 youdoo 库。
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator, Iterator
from datetime import timedelta

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.bootstrap.workflow_events import (
    apply_step_completed,
    enqueue_ready_steps,
)
from app.contexts.business.task_management.domain.state_machine import ACCEPTED
from app.contexts.foundations.execution.workflow_runtime.infrastructure.remote_completion import (
    apply_completed,
)
from app.core.config import get_settings
from app.core.internal_token import mint_internal_token
from app.main import app
from app.models import Base
from app.models.agent import AgentRole
from app.models.system import SysUser
from app.models.workflow import (
    STEP_RUNNING,
    STEP_SUCCEEDED,
    STEP_WAITING_HUMAN,
    OutboxEvent,
    WorkflowStep,
)
from app.platform.database import get_db
from app.platform.eventing.inbox import register_inbox_projector, unregister_inbox_projector
from app.platform.eventing.relay import EVENTS_SCOPE, StepReadyRelay
from app.platform.eventing.remote_step import (
    EXPERT_COMPLETED_EVENT,
    REMOTE_SENTINEL,
    STEP_READY_EVENT,
)
from app.platform.outbox.repository import utcnow
from tests import workflow_testkit as workflow_service
from tests.workflow_testkit import PlanStep, is_red_line

_REMOTE_SKILL = "data_query"
_SessionMaker = async_sessionmaker[AsyncSession]


@pytest.fixture(autouse=True)
def _remote_settings() -> Iterator[None]:
    """临时开 relay + allowlist + 私钥（自签自验）；用例后逐字还原（不污染其他测试）。"""
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    s = get_settings()
    saved = (
        s.internal_jwt_private_key,
        s.event_relay_enabled,
        s.event_remote_step_skills,
        s.event_remote_step_lease_seconds,
        s.event_inbox_peer_url,
    )
    s.internal_jwt_private_key = pem
    s.event_relay_enabled = True
    s.event_remote_step_skills = (_REMOTE_SKILL,)
    s.event_remote_step_lease_seconds = 3600
    s.event_inbox_peer_url = "http://test"
    yield
    (
        s.internal_jwt_private_key,
        s.event_relay_enabled,
        s.event_remote_step_skills,
        s.event_remote_step_lease_seconds,
        s.event_inbox_peer_url,
    ) = saved


@pytest.fixture
async def maker() -> AsyncGenerator[_SessionMaker, None]:
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


def _steps(*, red_line: bool) -> list[PlanStep]:
    # step0 走远端（skill=data_query 或红线 notify）；step1 依赖 step0，先不 ready。
    return [
        PlanStep(
            no=0,
            title="第一步",
            skill="notify" if red_line else _REMOTE_SKILL,
            instruction="执行第一步",
            depends_on=[],
        ),
        PlanStep(no=1, title="第二步", skill="deliver", instruction="执行第二步", depends_on=[0]),
    ]


async def _create_run(db: AsyncSession, *, red_line: bool = False) -> uuid.UUID:
    user = SysUser(username=f"u-{uuid.uuid4().hex[:8]}", password_hash="x", role_code="admin")
    role = AgentRole(
        name=f"agent-{uuid.uuid4().hex[:8]}",
        prompt_template="只执行测试任务",
        model_role="daily",
        tools=["none"],
    )
    db.add_all([user, role])
    await db.commit()
    skills = ("notify",) if red_line else (_REMOTE_SKILL,)
    get_settings().event_remote_step_skills = skills
    run = await workflow_service.create_workflow(
        db,
        request="先执行第一步再执行第二步",
        title="module3",
        creator_id=user.id,
        assignee_agent_id=role.id,
        steps=_steps(red_line=red_line),
        is_red_line=is_red_line,
    )
    await db.commit()
    return run.id


async def _outbox_types(db: AsyncSession) -> list[str]:
    return list((await db.execute(select(OutboxEvent.event_type))).scalars())


async def _advance_count(db: AsyncSession) -> int:
    return (await _outbox_types(db)).count("workflow.advance")


async def _first_step(db: AsyncSession, run_id: uuid.UUID) -> WorkflowStep:
    steps = await workflow_service.list_steps(db, run_id)
    return next(s for s in steps if s.step_no == 0)


def _completed_payload(step: WorkflowStep, *, content: str = "echo-ok") -> dict[str, object]:
    return {
        "workflow_run_id": str(step.workflow_run_id),
        "workflow_step_id": str(step.id),
        "step_version": step.version,
        "succeeded": True,
        "content": content,
        "error": None,
    }


async def test_remote_fork_parks_and_enqueues_step_ready(maker: _SessionMaker) -> None:
    async with maker() as db:
        run_id = await _create_run(db)
        await enqueue_ready_steps(db, run_id)
        await db.commit()
        step = await _first_step(db, run_id)
        assert step.status == STEP_RUNNING
        assert step.lease_owner == REMOTE_SENTINEL  # sentinel 停车
        types = await _outbox_types(db)
        assert STEP_READY_EVENT in types
        assert "workflow.step.execute" not in types  # 命中 allowlist 不走本地 execute


async def test_local_path_when_skill_not_in_allowlist(maker: _SessionMaker) -> None:
    async with maker() as db:
        run_id = await _create_run(db)
        get_settings().event_remote_step_skills = ()  # 回滚开关 → 全本地
        await enqueue_ready_steps(db, run_id)
        await db.commit()
        step = await _first_step(db, run_id)
        assert step.lease_owner is None  # 未停车
        types = await _outbox_types(db)
        assert "workflow.step.execute" in types
        assert STEP_READY_EVENT not in types


async def test_parked_step_not_reselected(maker: _SessionMaker) -> None:
    async with maker() as db:
        run_id = await _create_run(db)
        await enqueue_ready_steps(db, run_id)
        await db.commit()
        # 二次进入不应再出站（停车 step 非 ready）
        await enqueue_ready_steps(db, run_id)
        await db.commit()
        assert (await _outbox_types(db)).count(STEP_READY_EVENT) == 1


async def test_apply_completed_wakes_and_advances(maker: _SessionMaker) -> None:
    async with maker() as db:
        run_id = await _create_run(db)
        await enqueue_ready_steps(db, run_id)
        await db.commit()
        step = await _first_step(db, run_id)
        from app.contexts.business.task_management.infrastructure.sqlalchemy_adapter import (
            SQLAlchemyTaskManagementAdapter,
        )

        before = await _advance_count(db)  # 基线（含 create_workflow 启动 advance）
        applied = await apply_completed(
            db, _completed_payload(step), task_projection=SQLAlchemyTaskManagementAdapter(db)
        )
        await db.commit()
        assert applied is True
        step = await _first_step(db, run_id)
        assert step.status == STEP_SUCCEEDED
        assert await _advance_count(db) == before + 1  # 唤醒后新增一条推进


async def test_apply_completed_idempotent(maker: _SessionMaker) -> None:
    from app.contexts.business.task_management.infrastructure.sqlalchemy_adapter import (
        SQLAlchemyTaskManagementAdapter,
    )

    async with maker() as db:
        run_id = await _create_run(db)
        await enqueue_ready_steps(db, run_id)
        await db.commit()
        step = await _first_step(db, run_id)
        payload = _completed_payload(step)
        before = await _advance_count(db)
        first = await apply_completed(
            db, payload, task_projection=SQLAlchemyTaskManagementAdapter(db)
        )
        await db.commit()
        # 同 payload（旧 version）二投 → 预检/fence 挡下，不双写不双 advance
        second = await apply_completed(
            db, payload, task_projection=SQLAlchemyTaskManagementAdapter(db)
        )
        await db.commit()
        assert first is True and second is False
        assert await _advance_count(db) == before + 1  # 仅首投推进一次


async def test_red_line_step_waits_human_no_advance(maker: _SessionMaker) -> None:
    from app.contexts.business.task_management.infrastructure.sqlalchemy_adapter import (
        SQLAlchemyTaskManagementAdapter,
    )

    async with maker() as db:
        run_id = await _create_run(db, red_line=True)
        await enqueue_ready_steps(db, run_id)
        await db.commit()
        step = await _first_step(db, run_id)
        assert step.red_line is True and step.lease_owner == REMOTE_SENTINEL
        before = await _advance_count(db)
        applied = await apply_completed(
            db, _completed_payload(step), task_projection=SQLAlchemyTaskManagementAdapter(db)
        )
        await db.commit()
        assert applied is True
        step = await _first_step(db, run_id)
        assert step.status == STEP_WAITING_HUMAN  # 真人停点（AI 红线不破）
        assert await _advance_count(db) == before  # 不自动推进（唤醒未新增 advance）


async def test_expired_lease_degrades_to_local(maker: _SessionMaker) -> None:
    async with maker() as db:
        run_id = await _create_run(db)
        get_settings().event_remote_step_lease_seconds = 3600
        await enqueue_ready_steps(db, run_id)
        await db.commit()
        step = await _first_step(db, run_id)
        # 手动过期停车租约（模拟 expert 永不回发）
        step.lease_until = utcnow() - timedelta(seconds=1)
        await db.commit()
        # 关远端 allowlist 后重入 → expired 停车被 ready_steps 视为可重选 → 本地 execute 降级
        get_settings().event_remote_step_skills = ()
        await enqueue_ready_steps(db, run_id)
        await db.commit()
        assert "workflow.step.execute" in await _outbox_types(db)


async def test_step_ready_relay_injects_fresh_token_not_persisted(maker: _SessionMaker) -> None:
    async with maker() as db:
        run_id = await _create_run(db)
        await enqueue_ready_steps(db, run_id)
        await db.commit()
        row = (
            await db.execute(
                select(OutboxEvent).where(OutboxEvent.event_type == STEP_READY_EVENT)
            )
        ).scalar_one()
        assert "callback_token" not in (row.payload or {})  # 令牌绝不入库
        issuer = get_settings().internal_jwt_issuer
        relay = StepReadyRelay(peer_url="http://test", audience=issuer, source_service=issuer)
        injected = relay._payload(row)  # noqa: SLF001 - 测试直探投递期注入
        assert injected["callback_token"]  # 投递副本含新鲜令牌
        assert "callback_token" not in (row.payload or {})  # 原行仍不含


async def test_step_ready_relay_forwards_gateway_token_when_flagged(maker: _SessionMaker) -> None:
    """docs/23 §6.5：门控开→投递副本注入合法 gateway_token（aud=网关）；关→不注入。"""
    from app.core.internal_token import verify_internal_token

    async with maker() as db:
        run_id = await _create_run(db)
        await enqueue_ready_steps(db, run_id)
        await db.commit()
        row = (
            await db.execute(
                select(OutboxEvent).where(OutboxEvent.event_type == STEP_READY_EVENT)
            )
        ).scalar_one()
        s = get_settings()
        issuer = s.internal_jwt_issuer
        relay = StepReadyRelay(peer_url="http://test", audience=issuer, source_service=issuer)

        s.expert_forward_gateway_token = True
        try:
            token = relay._payload(row)["gateway_token"]  # noqa: SLF001
        finally:
            s.expert_forward_gateway_token = False
        claims = verify_internal_token(str(token), audience="ai-model-gateway")
        assert "llm:complete" in claims.scope
        assert "gateway_token" not in (row.payload or {})  # 绝不入库

        assert "gateway_token" not in relay._payload(row)  # noqa: SLF001 - 关→不注入


async def test_step_ready_relay_injects_capabilities_when_callback_url_set(
    maker: _SessionMaker,
) -> None:
    """docs/23 §6.8.5：配 capability_callback_url→投递副本注入合法 capabilities_token（aud=本
    issuer, scope=capabilities:execute）+ 回调地址 + 工具广告；空→不注入。三字段均绝不入库。"""
    from app.core.internal_token import verify_internal_token

    async with maker() as db:
        run_id = await _create_run(db)
        await enqueue_ready_steps(db, run_id)
        await db.commit()
        row = (
            await db.execute(
                select(OutboxEvent).where(OutboxEvent.event_type == STEP_READY_EVENT)
            )
        ).scalar_one()
        s = get_settings()
        issuer = s.internal_jwt_issuer
        relay = StepReadyRelay(peer_url="http://test", audience=issuer, source_service=issuer)

        s.capability_callback_url = "http://ai-youdoogo:8000"
        try:
            injected = relay._payload(row)  # noqa: SLF001
        finally:
            s.capability_callback_url = ""
        claims = verify_internal_token(str(injected["capabilities_token"]), audience=issuer)
        assert "capabilities:execute" in claims.scope
        assert injected["capabilities_callback_url"] == "http://ai-youdoogo:8000"
        assert "data_query" in str(injected["tool_advert"])
        assert "<<<CAPABILITY_CALL>>>" in str(injected["tool_advert"])
        for k in ("capabilities_token", "capabilities_callback_url", "tool_advert"):
            assert k not in (row.payload or {})  # 绝不入库

        off = relay._payload(row)  # noqa: SLF001 - 空→不注入
        assert "capabilities_token" not in off
        assert "tool_advert" not in off


async def test_completed_via_http_inbox_projects(maker: _SessionMaker) -> None:
    """completed 经真 /internal/events（验签+幂等落库+投影）唤醒停车 step。"""
    engine_sessions = maker

    async def override_db() -> AsyncGenerator[AsyncSession, None]:
        async with engine_sessions() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    # 入站门默认关 → 显式补挂 /internal/events 一次（app.state 去重）。
    if not getattr(app.state, "_eventing_mounted", False):
        from app.platform.eventing.entrypoints import router as eventing_router

        app.include_router(eventing_router)
        app.state._eventing_mounted = True
    register_inbox_projector(EXPERT_COMPLETED_EVENT, apply_step_completed)
    try:
        async with engine_sessions() as db:
            run_id = await _create_run(db)
            await enqueue_ready_steps(db, run_id)
            await db.commit()
            step = await _first_step(db, run_id)
            payload = _completed_payload(step)

        issuer = get_settings().internal_jwt_issuer
        token = mint_internal_token(service_id="expert", audience=issuer, scope=(EVENTS_SCOPE,))
        body = {
            "event_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{step.id}:{step.version}")),
            "event_type": EXPERT_COMPLETED_EVENT,
            "aggregate_type": "workflow_step",
            "aggregate_id": str(step.id),
            "payload": payload,
            "dedupe_key": f"expert-completed:{step.id}:v{step.version}",
        }
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/internal/events", json=body, headers={"Authorization": f"Bearer {token}"}
            )
        assert resp.status_code == 202
        async with engine_sessions() as db:
            woken = await _first_step(db, run_id)
            assert woken.status == STEP_SUCCEEDED
            parent = await workflow_service.get_task(db, woken.task_card_id)
            assert parent.status in (ACCEPTED, parent.status)  # 投影已刷新
    finally:
        unregister_inbox_projector(EXPERT_COMPLETED_EVENT)
        app.dependency_overrides.clear()
