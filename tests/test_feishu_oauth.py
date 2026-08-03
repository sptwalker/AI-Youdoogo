"""Feishu server-side user OAuth HTTP contract tests (no network or credentials)."""

import json
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import respx

from app.integrations.feishu.oauth import (
    AUTHORIZATION_URL,
    TOKEN_URL,
    USER_INFO_URL,
    FeishuOAuthClient,
    FeishuOAuthConfig,
    FeishuOAuthError,
)

CONFIG = FeishuOAuthConfig(
    app_id="cli_test_app",
    app_secret="test-secret-not-real",
    redirect_url="https://app.example.test/api/v1/auth/feishu/callback",
    secure_cookies=True,
)


def test_official_oauth_endpoints_are_pinned_independently() -> None:
    assert AUTHORIZATION_URL == "https://accounts.feishu.cn/open-apis/authen/v1/authorize"
    assert TOKEN_URL == "https://open.feishu.cn/open-apis/authen/v2/oauth/token"
    assert USER_INFO_URL == "https://open.feishu.cn/open-apis/authen/v1/user_info"


def test_authorization_url_uses_current_endpoint_and_pkce() -> None:
    url = FeishuOAuthClient(CONFIG).authorization_url("state-value", "challenge-value")
    parsed = urlsplit(url)
    query = parse_qs(parsed.query)
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == AUTHORIZATION_URL
    assert query == {
        "client_id": ["cli_test_app"],
        "response_type": ["code"],
        "redirect_uri": [CONFIG.redirect_url],
        "state": ["state-value"],
        "code_challenge": ["challenge-value"],
        "code_challenge_method": ["S256"],
    }
    assert "client_secret" not in query


@respx.mock
async def test_code_exchanged_for_user_token_then_open_id() -> None:
    token_route = respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "code": 0,
                "access_token": "user-access-token-test",
                "expires_in": 7200,
                "token_type": "Bearer",
            },
        )
    )
    user_route = respx.get(USER_INFO_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "code": 0,
                "msg": "success",
                "data": {
                    "open_id": "ou_test_123456",
                    "name": "测试用户",
                    "en_name": "Test User",
                    "avatar_url": "https://example.test/avatar.png",
                },
            },
        )
    )

    identity = await FeishuOAuthClient(CONFIG).identity_from_code(
        "authorization-code-test", "verifier-test-value"
    )
    assert identity.open_id == "ou_test_123456"
    assert identity.real_name == "测试用户"
    assert identity.en_name == "Test User"
    assert identity.avatar_url == "https://example.test/avatar.png"
    token_body = json.loads(token_route.calls.last.request.content)
    assert token_body == {
        "grant_type": "authorization_code",
        "client_id": CONFIG.app_id,
        "client_secret": CONFIG.app_secret,
        "code": "authorization-code-test",
        "redirect_uri": CONFIG.redirect_url,
        "code_verifier": "verifier-test-value",
    }
    assert user_route.calls.last.request.headers["Authorization"] == "Bearer user-access-token-test"
    assert all("tenant_access_token" not in str(call.request.url) for call in respx.calls)


@respx.mock
async def test_provider_failure_is_non_leaky() -> None:
    token_route = respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(
            400,
            json={"code": 20002, "error_description": "test-secret-not-real rejected"},
        )
    )
    user_route = respx.get(USER_INFO_URL).mock(
        return_value=httpx.Response(
            200,
            json={"code": 0, "msg": "success", "data": {"open_id": "ou_test_123456"}},
        )
    )
    with pytest.raises(FeishuOAuthError) as caught:
        await FeishuOAuthClient(CONFIG).identity_from_code(
            "authorization-code-test", "verifier-test-value"
        )
    assert caught.value.stage == "token exchange HTTP response"
    rendered = str(caught.value)
    assert "test-secret-not-real" not in rendered
    assert "authorization-code-test" not in rendered
    assert "20002" not in rendered
    assert token_route.called
    assert not user_route.called


@respx.mock
async def test_invalid_user_identity_is_rejected() -> None:
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(
            200,
            json={"code": 0, "access_token": "user-access-token-test"},
        )
    )
    respx.get(USER_INFO_URL).mock(
        return_value=httpx.Response(
            200,
            json={"code": 0, "msg": "success", "data": {"open_id": "invalid"}},
        )
    )

    with pytest.raises(FeishuOAuthError, match="user identity response"):
        await FeishuOAuthClient(CONFIG).identity_from_code(
            "authorization-code-test", "verifier-test-value"
        )


@respx.mock
async def test_network_failure_is_wrapped_without_request_details() -> None:
    request = httpx.Request("POST", TOKEN_URL)
    respx.post(TOKEN_URL).mock(
        side_effect=httpx.ConnectError("secret host detail", request=request)
    )

    with pytest.raises(FeishuOAuthError) as caught:
        await FeishuOAuthClient(CONFIG).identity_from_code(
            "authorization-code-test", "verifier-test-value"
        )
    assert caught.value.stage == "token exchange request"
    assert "secret host detail" not in str(caught.value)
