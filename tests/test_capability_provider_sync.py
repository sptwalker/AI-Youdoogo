"""同步 Capability Provider 服务面契约回环（docs/23 §6.7）。

离线（ASGITransport + 私钥自签自验 + in-memory StaticPool），注入**合成 side_effect=NONE 能力 +
stub handler**——只验传输门/鉴权/幂等，不依赖 data_query 真实 SQL 护栏与 seed（仿事件门禁合成事件）。
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.contexts.foundations.execution.capability_catalog.contracts.definition import (
    CapabilityDefinition,
    CapabilityRisk,
    CapabilitySideEffect,
)
from app.contexts.foundations.execution.capability_execution.application.ports import (
    HandlerExecutionResult,
)
from app.contexts.foundations.execution.capability_execution.contracts.execution import (
    CapabilityExecutionRequest,
    CapabilityPrincipal,
)
from app.contexts.foundations.execution.capability_execution.entrypoints import (
    CAPABILITIES_EXECUTE_SCOPE,
    PROVIDER_OVERRIDE_KEY,
    ProviderOverride,
)
from app.core.config import get_settings
from app.core.internal_token import mint_internal_token
from app.main import app
from app.models import Base
from app.platform.database import get_db


def _definition(key: str, side_effect: CapabilitySideEffect) -> CapabilityDefinition:
    return CapabilityDefinition(
        key=key,
        version="1.0",
        label=key,
        description="test",
        input_schema_json="{}",
        output_schema_json="{}",
        risk=CapabilityRisk.LOW,
        side_effect=side_effect,
        permission_keys=("data:read",),
        handler_identity="test",
    )


class _StubCatalog:
    def __init__(self, definition: CapabilityDefinition | None) -> None:
        self._definition = definition

    async def resolve(self, key: str, version: str | None) -> CapabilityDefinition | None:
        del key, version
        return self._definition


class _StubHandler:
    """回一条固定 note；captures principal 供断言 permission_keys 源自 definition。"""

    def __init__(self, principal: CapabilityPrincipal) -> None:
        self.principal = principal

    async def execute(
        self,
        request: CapabilityExecutionRequest,
        definition: CapabilityDefinition,
    ) -> HandlerExecutionResult:
        del request, definition
        return HandlerExecutionResult(notes=("ok",))


def _override(definition: CapabilityDefinition | None) -> ProviderOverride:
    return ProviderOverride(
        catalog=_StubCatalog(definition),
        handler=lambda _db, principal: _StubHandler(principal),
    )


@pytest.fixture(autouse=True)
def _internal_key() -> AsyncGenerator[None, None]:
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    settings = get_settings()
    original = settings.internal_jwt_private_key
    settings.internal_jwt_private_key = pem
    yield
    settings.internal_jwt_private_key = original


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """in-memory 单连接 + get_db 覆盖 + 条件挂载路由（临时 include capability_provider router）。"""
    from app.contexts.foundations.execution.capability_execution.entrypoints import (
        router as provider_router,
    )

    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def override_db() -> AsyncGenerator[AsyncSession, None]:
        async with sessions() as session:
            yield session

    # 默认关不挂路由；测试直接挂上（幂等：仅首次挂）。
    mounted = any(
        getattr(r, "path", None) == "/internal/capabilities/execute" for r in app.router.routes
    )
    if not mounted:
        app.include_router(provider_router)
    app.dependency_overrides[get_db] = override_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
    app.state.__dict__.pop(PROVIDER_OVERRIDE_KEY, None)
    await engine.dispose()


def _token(*scopes: str) -> str:
    return mint_internal_token(
        service_id="peer", audience=get_settings().internal_jwt_issuer, scope=tuple(scopes)
    )


def _body(**over: object) -> dict[str, object]:
    body: dict[str, object] = {
        "capability_key": "syncable",
        "capability_version": "1.0",
        "arguments": {},
        "expert_id": str(uuid.uuid4()),
    }
    body.update(over)
    return body


async def test_sync_local_allowed(client: AsyncClient) -> None:
    """SYNC_LOCAL 能力 + 有效 scope → 200，封套 status=succeeded。"""
    app.state.capability_provider_override = _override(
        _definition("syncable", CapabilitySideEffect.NONE)
    )
    resp = await client.post(
        "/internal/capabilities/execute",
        json=_body(),
        headers={"Authorization": f"Bearer {_token(CAPABILITIES_EXECUTE_SCOPE)}"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "succeeded" and data["notes"] == ["ok"]


async def test_event_gated_rejected_409(client: AsyncClient) -> None:
    """有写副作用（EVENT_GATED）→ 409（协议层资格拒绝，非业务结果）。"""
    app.state.capability_provider_override = _override(
        _definition("writer", CapabilitySideEffect.INTERNAL_WRITE)
    )
    resp = await client.post(
        "/internal/capabilities/execute",
        json=_body(capability_key="writer"),
        headers={"Authorization": f"Bearer {_token(CAPABILITIES_EXECUTE_SCOPE)}"},
    )
    assert resp.status_code == 409


async def test_unregistered_rejected_envelope(client: AsyncClient) -> None:
    """未注册 → 封套 status=rejected（200，业务拒绝而非协议拒绝）。"""
    app.state.capability_provider_override = _override(None)
    resp = await client.post(
        "/internal/capabilities/execute",
        json=_body(capability_key="ghost"),
        headers={"Authorization": f"Bearer {_token(CAPABILITIES_EXECUTE_SCOPE)}"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "rejected" and data["error"] == "not_registered"


async def test_rejects_bad_auth(client: AsyncClient) -> None:
    """无令牌 → 401/403；坏令牌 → 401。"""
    app.state.capability_provider_override = _override(
        _definition("syncable", CapabilitySideEffect.NONE)
    )
    no_token = await client.post("/internal/capabilities/execute", json=_body())
    assert no_token.status_code in (401, 403)
    bad = await client.post(
        "/internal/capabilities/execute",
        json=_body(),
        headers={"Authorization": "Bearer not-a-jwt"},
    )
    assert bad.status_code == 401


async def test_missing_scope_403(client: AsyncClient) -> None:
    """有效令牌但缺 capabilities:execute scope → 403。"""
    app.state.capability_provider_override = _override(
        _definition("syncable", CapabilitySideEffect.NONE)
    )
    resp = await client.post(
        "/internal/capabilities/execute",
        json=_body(),
        headers={"Authorization": f"Bearer {_token()}"},
    )
    assert resp.status_code == 403


async def test_idempotent_replay(client: AsyncClient) -> None:
    """同 idempotency_key POST 两次 → 同 invocation_id，第二次 replayed=True。"""
    app.state.capability_provider_override = _override(
        _definition("syncable", CapabilitySideEffect.NONE)
    )
    body = _body(idempotency_key=f"idem:{uuid.uuid4()}")
    headers = {"Authorization": f"Bearer {_token(CAPABILITIES_EXECUTE_SCOPE)}"}
    first = (await client.post("/internal/capabilities/execute", json=body, headers=headers)).json()
    second = (
        await client.post("/internal/capabilities/execute", json=body, headers=headers)
    ).json()
    assert first["data"]["invocation_id"] == second["data"]["invocation_id"]
    assert second["data"]["replayed"] is True


# --- _RegistryHandler.execute 真实 dispatch（端点测试注入 stub handler 绕过它，故直测 106-139）---


class _StubExec:
    """脚本化 executor：execute 回定 SkillResult，验 _RegistryHandler 的 legacy→Handler 映射。"""

    async def execute(self, db: object, role: object, request: object, context: object) -> object:
        from app.agents.contracts import SkillResult

        return SkillResult(notes=["n"], datasets=[{"a": 1}], artifacts=[{"b": 2}])


async def test_registry_handler_maps_skill_result(monkeypatch: pytest.MonkeyPatch) -> None:
    """注册键 → executor 跑一次，legacy 结果映为 HandlerExecutionResult 紧凑 JSON。"""
    from app.agents.skill_registry import REGISTRY, Skill
    from app.contexts.foundations.execution.capability_execution.entrypoints.http import (
        _RegistryHandler,
    )

    monkeypatch.setitem(
        REGISTRY,
        "stubcap",
        Skill(_definition("stubcap", CapabilitySideEffect.NONE), executor_factory=_StubExec),
    )
    principal = CapabilityPrincipal(principal_id=None, expert_id=uuid.uuid4())
    request = CapabilityExecutionRequest(
        capability_key="stubcap", action_index=0, arguments_json="{}", principal=principal
    )

    result = await _RegistryHandler(object(), principal).execute(  # type: ignore[arg-type]
        request, _definition("stubcap", CapabilitySideEffect.NONE)
    )

    assert result.notes == ("n",)
    assert result.dataset_json == ('{"a":1}',)
    assert result.artifact_json == ('{"b":2}',)


async def test_registry_handler_unregistered_raises() -> None:
    """未注册键 → LookupError（handler 不可用）；端点层据此走 500 兜底。"""
    from app.contexts.foundations.execution.capability_execution.entrypoints.http import (
        _RegistryHandler,
    )

    principal = CapabilityPrincipal(principal_id=None, expert_id=uuid.uuid4())
    request = CapabilityExecutionRequest(
        capability_key="ghostcap", action_index=0, arguments_json="{}", principal=principal
    )

    with pytest.raises(LookupError):
        await _RegistryHandler(object(), principal).execute(  # type: ignore[arg-type]
            request, _definition("ghostcap", CapabilitySideEffect.NONE)
        )
