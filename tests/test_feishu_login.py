"""Feishu login state, identity gate, and one-time application JWT exchange tests."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import Request, Response
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.v1.auth import EXCHANGE_COOKIE, feishu_exchange, feishu_start, feishu_status
from app.core.database import get_db
from app.core.oauth_query_scrub import OAuthCallbackQueryScrubMiddleware
from app.core.security import hash_password
from app.integrations.feishu.oauth import FeishuIdentity, FeishuOAuthConfig, FeishuOAuthError
from app.main import app
from app.models import Base
from app.models.system import SysUser
from app.services.feishu_login import (
    SUPPORT_CAPTURE_KEY,
    SUPPORT_CAPTURE_TTL_SECONDS,
    FeishuLoginService,
    InvalidOAuthCallback,
    InvalidOAuthState,
    OAuthExchangeData,
    OAuthStateData,
    OAuthUnavailable,
    RedisOAuthStore,
    get_feishu_login_service,
)

TEST_CONFIG = FeishuOAuthConfig(
    app_id="cli_test_app",
    app_secret="test-secret-not-real",
    redirect_url="http://test/api/v1/auth/feishu/callback",
    secure_cookies=False,
)


class MemoryOAuthStore:
    """Test store with the same conditional and one-time consume semantics as Redis."""

    def __init__(self) -> None:
        self.now = 0
        self.states: dict[str, tuple[OAuthStateData, int]] = {}
        self.exchanges: dict[str, tuple[OAuthExchangeData, int]] = {}
        self.denied_identity: tuple[str, int] | None = None
        self.capture_unavailable = False

    async def save_state(self, state_digest: str, data: OAuthStateData, ttl: int) -> bool:
        if state_digest in self.states:
            return False
        self.states[state_digest] = (data, self.now + ttl)
        return True

    async def consume_state(
        self, state_digest: str, binding_digest: str
    ) -> OAuthStateData | None:
        saved = self.states.get(state_digest)
        if saved is None:
            return None
        data, expires_at = saved
        if self.now >= expires_at:
            self.states.pop(state_digest, None)
            return None
        if data.binding_digest != binding_digest:
            return None
        self.states.pop(state_digest, None)
        return data

    async def save_exchange(
        self, handle_digest: str, data: OAuthExchangeData, ttl: int
    ) -> bool:
        if handle_digest in self.exchanges:
            return False
        self.exchanges[handle_digest] = (data, self.now + ttl)
        return True

    async def consume_exchange(self, handle_digest: str) -> OAuthExchangeData | None:
        saved = self.exchanges.pop(handle_digest, None)
        if saved is None:
            return None
        data, expires_at = saved
        return data if self.now < expires_at else None

    async def save_denied_identity(self, open_id: str, ttl: int) -> bool:
        if self.capture_unavailable:
            raise OAuthUnavailable
        if self.denied_identity is not None:
            _, expires_at = self.denied_identity
            if self.now < expires_at:
                return False
        self.denied_identity = (open_id, self.now + ttl)
        return True

    async def consume_denied_identity(self) -> str | None:
        if self.capture_unavailable:
            raise OAuthUnavailable
        saved = self.denied_identity
        self.denied_identity = None
        if saved is None:
            return None
        open_id, expires_at = saved
        return open_id if self.now < expires_at else None

    async def close(self) -> None:
        return None


@dataclass
class FakeProvider:
    identities: dict[str, str]
    exchange_calls: int = 0
    failure_stage: str | None = None

    def authorization_url(self, state: str, code_challenge: str) -> str:
        return (
            "https://accounts.feishu.cn/open-apis/authen/v1/authorize"
            f"?state={state}&code_challenge={code_challenge}"
        )

    async def identity_from_code(self, code: str, code_verifier: str) -> FeishuIdentity:
        self.exchange_calls += 1
        if self.failure_stage is not None:
            raise FeishuOAuthError(self.failure_stage)
        return FeishuIdentity(open_id=self.identities[code])


def make_service(
    store: MemoryOAuthStore | None = None,
    provider: FakeProvider | None = None,
) -> tuple[FeishuLoginService, MemoryOAuthStore, FakeProvider]:
    actual_store = store or MemoryOAuthStore()
    actual_provider = provider or FakeProvider({})
    service = FeishuLoginService(
        actual_store,
        config_loader=lambda: TEST_CONFIG,
        client_factory=lambda _config: actual_provider,
    )
    return service, actual_store, actual_provider


async def test_state_binding_expiry_replay_and_tampering() -> None:
    service, store, _ = make_service()

    started = await service.start("/tasks")
    state = parse_qs(urlsplit(started.authorization_url).query)["state"][0]
    with pytest.raises(InvalidOAuthState):
        await service.consume_callback_state(state, "tampered-binding")
    transaction = await service.consume_callback_state(state, started.browser_binding)
    assert transaction.return_to == "/tasks"
    with pytest.raises(InvalidOAuthState):
        await service.consume_callback_state(state, started.browser_binding)

    expired = await service.start("/")
    expired_state = parse_qs(urlsplit(expired.authorization_url).query)["state"][0]
    store.now += 601
    with pytest.raises(InvalidOAuthState):
        await service.consume_callback_state(expired_state, expired.browser_binding)


async def test_support_capture_is_fixed_ttl_non_overwriting_and_one_time() -> None:
    service, store, _ = make_service()

    assert await service.capture_denied_identity("ou_first_123456") is True
    assert await service.capture_denied_identity("ou_second_123456") is False
    assert await service.consume_captured_denied_identity() == "ou_first_123456"
    assert await service.consume_captured_denied_identity() is None

    assert await service.capture_denied_identity("ou_expiring_123456") is True
    store.now += SUPPORT_CAPTURE_TTL_SECONDS
    assert await service.consume_captured_denied_identity() is None
    assert await service.capture_denied_identity("ou_after_expiry_123456") is True


async def test_support_capture_rejects_invalid_identity() -> None:
    service, store, _ = make_service()

    assert await service.capture_denied_identity("invalid") is False
    assert store.denied_identity is None


async def test_redis_support_capture_uses_fixed_namespaced_key_and_atomic_consume() -> None:
    class RecordingRedis:
        def __init__(self) -> None:
            self.set_call: tuple[tuple[Any, ...], dict[str, Any]] | None = None
            self.eval_call: tuple[Any, ...] | None = None

        async def set(self, *args: Any, **kwargs: Any) -> bool:
            self.set_call = (args, kwargs)
            return True

        async def eval(self, *args: Any) -> str:
            self.eval_call = args
            return "ou_captured_123456"

    client = RecordingRedis()
    store = RedisOAuthStore("redis://unused")
    store._client = cast(Any, client)

    assert await store.save_denied_identity("ou_captured_123456", 600) is True
    assert client.set_call == (
        (SUPPORT_CAPTURE_KEY, "ou_captured_123456"),
        {"ex": 600, "nx": True},
    )
    assert await store.consume_denied_identity() == "ou_captured_123456"
    assert client.eval_call is not None
    assert client.eval_call[1:] == (1, SUPPORT_CAPTURE_KEY)


async def test_authorization_code_is_opaque_but_rejects_controls() -> None:
    provider = FakeProvider({"opaque.code+/=~": "ou_bound_123456"})
    service, _, _ = make_service(provider=provider)
    started = await service.start("/")
    state = parse_qs(urlsplit(started.authorization_url).query)["state"][0]
    transaction = await service.consume_callback_state(state, started.browser_binding)

    completed = await service.exchange_code(transaction, "opaque.code+/=~")
    assert completed.identity.open_id == "ou_bound_123456"

    with pytest.raises(InvalidOAuthCallback):
        await service.exchange_code(transaction, "line\nbreak")


async def test_unavailable_feature_status_and_start_return_to_login() -> None:
    def unavailable_config() -> FeishuOAuthConfig:
        raise OAuthUnavailable

    service = FeishuLoginService(MemoryOAuthStore(), config_loader=unavailable_config)
    response = Response()
    status = await feishu_status(response, service)
    assert status["data"] == {"enabled": False}
    assert response.headers["cache-control"] == "no-store"

    started = await feishu_start(service)
    assert started.status_code == 303
    assert started.headers["location"] == "/login?feishu=unavailable"


def exchange_request(handle: str, origin: str | None) -> Request:
    headers = [(b"cookie", f"{EXCHANGE_COOKIE}={handle}".encode())]
    if origin is not None:
        headers.append((b"origin", origin.encode()))
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/api/v1/auth/feishu/exchange",
            "raw_path": b"/api/v1/auth/feishu/exchange",
            "query_string": b"",
            "headers": headers,
            "client": ("127.0.0.1", 1234),
            "server": ("test", 80),
        }
    )


async def test_origin_rejection_does_not_consume_or_clear_exchange() -> None:
    service, _, _ = make_service()
    handle, _ = await service.create_exchange(
        access_token="app-jwt-test",
        token_type="bearer",
        expires_in=3600,
        redirect_to="/tasks",
    )

    denied = await feishu_exchange(exchange_request(handle, "https://evil.example"), service)
    assert denied.status_code == 403
    assert "set-cookie" not in denied.headers

    accepted = await feishu_exchange(exchange_request(handle, "http://test"), service)
    assert accepted.status_code == 200
    assert json.loads(accepted.body)["data"]["redirect_to"] == "/tasks"


async def test_callback_query_is_removed_before_access_logging() -> None:
    seen: dict[str, object] = {}

    async def downstream(scope: dict, _receive: object, send: object) -> None:
        seen.update(scope)
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(_message: dict[str, object]) -> None:
        return None

    middleware = OAuthCallbackQueryScrubMiddleware(downstream)  # type: ignore[arg-type]
    scope = {
        "type": "http",
        "path": "/api/v1/auth/feishu/callback",
        "query_string": b"code=sensitive-code-test&state=state-test",
        "state": {},
    }
    await middleware(scope, receive, send)  # type: ignore[arg-type]
    assert seen["query_string"] == b""
    assert seen["state"] == {
        "feishu_oauth_query": {"code": "sensitive-code-test", "state": "state-test"}
    }


@pytest.fixture
async def oauth_client() -> AsyncGenerator[
    tuple[AsyncClient, FakeProvider, FeishuLoginService, MemoryOAuthStore], None
]:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        session.add_all(
            [
                SysUser(
                    username="bound",
                    password_hash=hash_password("bound-pass-88"),
                    role_code="member",
                    feishu_open_id="ou_bound_123456",
                ),
                SysUser(
                    username="disabled",
                    password_hash=hash_password("disabled-pass-88"),
                    role_code="member",
                    feishu_open_id="ou_disabled_123456",
                    is_active=False,
                ),
                SysUser(
                    username="unbound",
                    password_hash=hash_password("unbound-pass-88"),
                    role_code="member",
                ),
                SysUser(
                    username="deleted",
                    password_hash=hash_password("deleted-pass-88"),
                    role_code="member",
                    feishu_open_id="ou_deleted_123456",
                    is_delete=True,
                ),
            ]
        )
        await session.commit()

    async def override_db() -> AsyncGenerator:
        async with factory() as session:
            yield session

    provider = FakeProvider({})
    service, store, _ = make_service(provider=provider)
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_feishu_login_service] = lambda: service
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", follow_redirects=False
    ) as client:
        yield client, provider, service, store
    app.dependency_overrides.clear()
    await engine.dispose()


async def begin(client: AsyncClient, return_to: str = "/") -> str:
    response = await client.get(
        "/api/v1/auth/feishu/start", params={"return_to": return_to}
    )
    assert response.status_code == 303, response.text
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=lax" in response.headers["set-cookie"]
    return parse_qs(urlsplit(response.headers["location"]).query)["state"][0]


async def callback(client: AsyncClient, state: str, code: str) -> object:
    return await client.get(
        "/api/v1/auth/feishu/callback",
        params={"state": state, "code": code},
    )


async def test_callback_handoff_has_no_token_in_redirect_and_is_one_time(
    oauth_client: tuple[AsyncClient, FakeProvider, FeishuLoginService, MemoryOAuthStore],
) -> None:
    client, provider, service, _ = oauth_client
    provider.identities["good-code"] = "ou_bound_123456"
    state = await begin(client, "/tasks")
    response = await callback(client, state, "good-code")
    assert response.status_code == 303
    assert response.headers["location"] == "/login?feishu=success"
    assert "access_token" not in response.headers["location"]
    assert "good-code" not in response.headers["location"]
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=strict" in response.headers["set-cookie"]

    exchange = await client.post(
        "/api/v1/auth/feishu/exchange", headers={"Origin": "http://test"}
    )
    assert exchange.status_code == 200, exchange.text
    token_data = exchange.json()["data"]
    assert token_data["access_token"]
    assert token_data["redirect_to"] == "/tasks"
    me = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token_data['access_token']}"},
    )
    assert me.status_code == 200
    assert me.json()["data"]["username"] == "bound"

    replay = await client.post(
        "/api/v1/auth/feishu/exchange", headers={"Origin": "http://test"}
    )
    assert replay.status_code == 400
    assert await service.consume_captured_denied_identity() is None


async def test_status_reports_configured_feature_without_exposing_config(
    oauth_client: tuple[AsyncClient, FakeProvider, FeishuLoginService, MemoryOAuthStore],
) -> None:
    client, _, _, _ = oauth_client
    response = await client.get("/api/v1/auth/feishu/status")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {"code": 0, "msg": "ok", "data": {"enabled": True}}


async def test_cancelled_callback_consumes_state_without_calling_provider(
    oauth_client: tuple[AsyncClient, FakeProvider, FeishuLoginService, MemoryOAuthStore],
) -> None:
    client, provider, service, _ = oauth_client
    state = await begin(client)
    response = await client.get(
        "/api/v1/auth/feishu/callback",
        params={"state": state, "error": "access_denied"},
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/login?feishu=cancelled"
    assert provider.exchange_calls == 0

    replay = await callback(client, state, "unused-code")
    assert replay.headers["location"] == "/login?feishu=invalid_state"
    assert await service.consume_captured_denied_identity() is None


async def test_missing_code_and_provider_failure_are_safe_login_errors(
    oauth_client: tuple[AsyncClient, FakeProvider, FeishuLoginService, MemoryOAuthStore],
) -> None:
    client, provider, service, _ = oauth_client
    missing_code_state = await begin(client)
    missing = await callback(client, missing_code_state, "")
    assert missing.headers["location"] == "/login?feishu=error"
    assert provider.exchange_calls == 0

    provider.failure_stage = "token exchange rejected"
    provider_failure_state = await begin(client)
    failed = await callback(client, provider_failure_state, "provider-code")
    assert failed.headers["location"] == "/login?feishu=error"
    assert provider.exchange_calls == 1
    assert await service.consume_captured_denied_identity() is None


@pytest.mark.parametrize(
    "open_id",
    ["ou_unknown_123456", "ou_disabled_123456", "ou_deleted_123456"],
)
async def test_unknown_unbound_disabled_and_deleted_users_share_denial(
    oauth_client: tuple[AsyncClient, FakeProvider, FeishuLoginService, MemoryOAuthStore],
    open_id: str,
) -> None:
    client, provider, service, _ = oauth_client
    code = f"code-{open_id}"
    provider.identities[code] = open_id
    state = await begin(client)
    response = await callback(client, state, code)
    assert response.status_code == 303
    assert response.headers["location"] == "/login?feishu=access_required"
    assert await service.consume_captured_denied_identity() == open_id


async def test_later_denial_does_not_overwrite_live_support_capture(
    oauth_client: tuple[AsyncClient, FakeProvider, FeishuLoginService, MemoryOAuthStore],
) -> None:
    client, provider, service, _ = oauth_client
    provider.identities.update(
        {
            "first-denied-code": "ou_first_denied_123456",
            "second-denied-code": "ou_second_denied_123456",
        }
    )

    first_state = await begin(client)
    first = await callback(client, first_state, "first-denied-code")
    second_state = await begin(client)
    second = await callback(client, second_state, "second-denied-code")

    assert first.headers["location"] == "/login?feishu=access_required"
    assert second.headers["location"] == "/login?feishu=access_required"
    assert await service.consume_captured_denied_identity() == "ou_first_denied_123456"


async def test_support_capture_outage_keeps_generic_denial(
    oauth_client: tuple[AsyncClient, FakeProvider, FeishuLoginService, MemoryOAuthStore],
) -> None:
    client, provider, _, store = oauth_client
    provider.identities["capture-outage-code"] = "ou_capture_outage_123456"
    store.capture_unavailable = True

    state = await begin(client)
    response = await callback(client, state, "capture-outage-code")

    assert response.status_code == 303
    assert response.headers["location"] == "/login?feishu=access_required"


async def test_external_return_to_rejected(
    oauth_client: tuple[AsyncClient, FakeProvider, FeishuLoginService, MemoryOAuthStore],
) -> None:
    client, _, _, _ = oauth_client
    for value in (
        "https://evil.example/",
        "//evil.example/",
        "/%5C%5Cevil.example",
        "http://[invalid",
    ):
        response = await client.get(
            "/api/v1/auth/feishu/start", params={"return_to": value}
        )
        assert response.status_code == 400, value


async def test_invalid_state_never_calls_feishu(
    oauth_client: tuple[AsyncClient, FakeProvider, FeishuLoginService, MemoryOAuthStore],
) -> None:
    client, provider, service, _ = oauth_client
    state = await begin(client)
    response = await callback(client, f"{state}tampered", "unused-code")
    assert response.status_code == 303
    assert response.headers["location"] == "/login?feishu=invalid_state"
    assert provider.exchange_calls == 0
    assert await service.consume_captured_denied_identity() is None


async def test_cross_origin_exchange_rejected_before_consumption(
    oauth_client: tuple[AsyncClient, FakeProvider, FeishuLoginService, MemoryOAuthStore],
) -> None:
    client, provider, _, _ = oauth_client
    provider.identities["origin-code"] = "ou_bound_123456"
    state = await begin(client)
    await callback(client, state, "origin-code")
    denied = await client.post(
        "/api/v1/auth/feishu/exchange", headers={"Origin": "https://evil.example"}
    )
    assert denied.status_code == 403
    assert "set-cookie" not in denied.headers

    accepted = await client.post(
        "/api/v1/auth/feishu/exchange", headers={"Origin": "http://test"}
    )
    assert accepted.status_code == 200


async def test_exchange_requires_browser_origin_without_destroying_handoff(
    oauth_client: tuple[AsyncClient, FakeProvider, FeishuLoginService, MemoryOAuthStore],
) -> None:
    client, provider, _, _ = oauth_client
    provider.identities["missing-origin-code"] = "ou_bound_123456"
    state = await begin(client)
    await callback(client, state, "missing-origin-code")

    denied = await client.post("/api/v1/auth/feishu/exchange")
    assert denied.status_code == 403
    assert "set-cookie" not in denied.headers

    accepted = await client.post(
        "/api/v1/auth/feishu/exchange", headers={"Origin": "http://test"}
    )
    assert accepted.status_code == 200
