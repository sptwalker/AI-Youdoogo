"""Feishu login state, identity gate, and one-time application JWT exchange tests."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import get_db
from app.core.oauth_query_scrub import OAuthCallbackQueryScrubMiddleware
from app.core.security import hash_password
from app.integrations.feishu.oauth import FeishuIdentity, FeishuOAuthConfig
from app.main import app
from app.models import Base
from app.models.system import SysUser
from app.services.feishu_login import (
    FeishuLoginService,
    InvalidOAuthState,
    OAuthExchangeData,
    OAuthStateData,
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

    async def close(self) -> None:
        return None


@dataclass
class FakeProvider:
    identities: dict[str, str]
    exchange_calls: int = 0

    def authorization_url(self, state: str, code_challenge: str) -> str:
        return (
            "https://accounts.feishu.cn/open-apis/authen/v1/authorize"
            f"?state={state}&code_challenge={code_challenge}"
        )

    async def identity_from_code(self, code: str, code_verifier: str) -> FeishuIdentity:
        self.exchange_calls += 1
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
async def oauth_client() -> AsyncGenerator[tuple[AsyncClient, FakeProvider], None]:
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
    service, _, _ = make_service(provider=provider)
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_feishu_login_service] = lambda: service
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", follow_redirects=False
    ) as client:
        yield client, provider
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
    oauth_client: tuple[AsyncClient, FakeProvider],
) -> None:
    client, provider = oauth_client
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


@pytest.mark.parametrize(
    "open_id",
    ["ou_unknown_123456", "ou_disabled_123456", "ou_deleted_123456"],
)
async def test_unknown_unbound_disabled_and_deleted_users_share_denial(
    oauth_client: tuple[AsyncClient, FakeProvider], open_id: str
) -> None:
    client, provider = oauth_client
    code = f"code-{open_id}"
    provider.identities[code] = open_id
    state = await begin(client)
    response = await callback(client, state, code)
    assert response.status_code == 303
    assert response.headers["location"] == "/login?feishu=access_required"


async def test_external_return_to_rejected(
    oauth_client: tuple[AsyncClient, FakeProvider],
) -> None:
    client, _ = oauth_client
    for value in ("https://evil.example/", "//evil.example/", "/%5C%5Cevil.example"):
        response = await client.get(
            "/api/v1/auth/feishu/start", params={"return_to": value}
        )
        assert response.status_code == 400, value


async def test_invalid_state_never_calls_feishu(
    oauth_client: tuple[AsyncClient, FakeProvider],
) -> None:
    client, provider = oauth_client
    state = await begin(client)
    response = await callback(client, f"{state}tampered", "unused-code")
    assert response.status_code == 303
    assert response.headers["location"] == "/login?feishu=invalid_state"
    assert provider.exchange_calls == 0


async def test_cross_origin_exchange_rejected_before_consumption(
    oauth_client: tuple[AsyncClient, FakeProvider],
) -> None:
    client, provider = oauth_client
    provider.identities["origin-code"] = "ou_bound_123456"
    state = await begin(client)
    await callback(client, state, "origin-code")
    denied = await client.post(
        "/api/v1/auth/feishu/exchange", headers={"Origin": "https://evil.example"}
    )
    assert denied.status_code == 403
