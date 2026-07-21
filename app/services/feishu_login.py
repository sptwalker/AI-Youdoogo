"""Feishu login orchestration facade over focused config and transient stores."""

from __future__ import annotations

import secrets
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

from app.core import runtime_config as runtime_config
from app.core.config import get_settings as get_settings
from app.integrations.feishu.oauth import (
    FeishuIdentity,
    FeishuOAuthClient,
    FeishuOAuthConfig,
    pkce_challenge,
)
from app.services.feishu_oauth_config import (
    CALLBACK_PATH,
    PRODUCTION_REDIRECT_URL,
    SAFE_TOKEN,
    VISIBLE_OAUTH_VALUE,
    InvalidOAuthCallback,
    InvalidOAuthState,
    InvalidReturnTo,
    OAuthUnavailable,
    digest,
    load_oauth_config,
    normalize_return_to,
)
from app.services.feishu_oauth_store import (
    EXCHANGE_TTL_SECONDS,
    STATE_TTL_SECONDS,
    OAuthExchangeData,
    OAuthStateData,
    OAuthStore,
    RedisOAuthStore,
)

__all__ = [
    "CALLBACK_PATH",
    "EXCHANGE_TTL_SECONDS",
    "PRODUCTION_REDIRECT_URL",
    "STATE_TTL_SECONDS",
    "FeishuLoginService",
    "InvalidOAuthCallback",
    "InvalidOAuthState",
    "InvalidReturnTo",
    "OAuthCompletion",
    "OAuthExchangeData",
    "OAuthStart",
    "OAuthStateData",
    "OAuthUnavailable",
    "RedisOAuthStore",
    "feishu_login_service",
    "get_feishu_login_service",
    "load_oauth_config",
    "normalize_return_to",
]


class OAuthProvider(Protocol):
    def authorization_url(self, state: str, code_challenge: str) -> str: ...

    async def identity_from_code(
        self, code: str, code_verifier: str
    ) -> FeishuIdentity: ...


@dataclass(frozen=True)
class OAuthStart:
    authorization_url: str
    browser_binding: str
    secure_cookies: bool


@dataclass(frozen=True)
class OAuthCompletion:
    identity: FeishuIdentity
    return_to: str


class FeishuLoginService:
    """Coordinate state, PKCE, identity, and one-time application JWT handoff."""

    def __init__(
        self,
        store: OAuthStore,
        *,
        config_loader: Callable[[], FeishuOAuthConfig] = load_oauth_config,
        client_factory: Callable[[FeishuOAuthConfig], OAuthProvider] = FeishuOAuthClient,
    ) -> None:
        self.store = store
        self.config_loader = config_loader
        self.client_factory = client_factory

    def is_available(self) -> bool:
        try:
            self.config_loader()
        except OAuthUnavailable:
            return False
        return True

    async def start(self, return_to: str | None) -> OAuthStart:
        config = self.config_loader()
        safe_return_to = normalize_return_to(return_to)
        for _ in range(3):
            state = secrets.token_urlsafe(32)
            browser_binding = secrets.token_urlsafe(32)
            code_verifier = secrets.token_urlsafe(64)
            data = OAuthStateData(
                binding_digest=digest(browser_binding),
                code_verifier=code_verifier,
                return_to=safe_return_to,
            )
            if await self.store.save_state(digest(state), data, STATE_TTL_SECONDS):
                provider = self.client_factory(config)
                return OAuthStart(
                    authorization_url=provider.authorization_url(
                        state, pkce_challenge(code_verifier)
                    ),
                    browser_binding=browser_binding,
                    secure_cookies=config.secure_cookies,
                )
        raise OAuthUnavailable

    async def consume_callback_state(
        self, state: str, browser_binding: str
    ) -> OAuthStateData:
        if (
            not state
            or len(state) > 256
            or SAFE_TOKEN.fullmatch(state) is None
            or not browser_binding
            or len(browser_binding) > 256
            or SAFE_TOKEN.fullmatch(browser_binding) is None
        ):
            raise InvalidOAuthState
        binding_digest = digest(browser_binding)
        data = await self.store.consume_state(digest(state), binding_digest)
        if data is None or not secrets.compare_digest(data.binding_digest, binding_digest):
            raise InvalidOAuthState
        return data

    async def exchange_code(
        self, transaction: OAuthStateData, code: str
    ) -> OAuthCompletion:
        if not code or len(code) > 512 or VISIBLE_OAUTH_VALUE.fullmatch(code) is None:
            raise InvalidOAuthCallback
        config = self.config_loader()
        identity = await self.client_factory(config).identity_from_code(
            code, transaction.code_verifier
        )
        return OAuthCompletion(identity=identity, return_to=transaction.return_to)

    async def create_exchange(
        self, *, access_token: str, token_type: str, expires_in: int, redirect_to: str
    ) -> tuple[str, bool]:
        config = self.config_loader()
        data = OAuthExchangeData(
            access_token=access_token,
            token_type=token_type,
            expires_in=expires_in,
            redirect_to=normalize_return_to(redirect_to),
        )
        for _ in range(3):
            handle = secrets.token_urlsafe(32)
            if await self.store.save_exchange(digest(handle), data, EXCHANGE_TTL_SECONDS):
                return handle, config.secure_cookies
        raise OAuthUnavailable

    async def consume_exchange(self, handle: str) -> OAuthExchangeData:
        if not handle or len(handle) > 256 or SAFE_TOKEN.fullmatch(handle) is None:
            raise InvalidOAuthState
        data = await self.store.consume_exchange(digest(handle))
        if data is None:
            raise InvalidOAuthState
        return data

    def expected_origin(self) -> str:
        parsed = urlsplit(self.config_loader().redirect_url)
        return f"{parsed.scheme}://{parsed.netloc}"

    async def close(self) -> None:
        await self.store.close()


_store = RedisOAuthStore(get_settings().redis_url)
feishu_login_service = FeishuLoginService(_store)


def get_feishu_login_service() -> FeishuLoginService:
    return feishu_login_service
