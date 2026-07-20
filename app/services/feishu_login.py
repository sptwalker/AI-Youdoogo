"""Application-local Feishu login flow and one-time browser handoff."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any, Protocol
from urllib.parse import unquote, urlsplit

import redis.asyncio as aioredis
from redis.exceptions import RedisError

from app.core import runtime_config
from app.core.config import get_settings
from app.integrations.feishu.oauth import (
    FeishuIdentity,
    FeishuOAuthClient,
    FeishuOAuthConfig,
    pkce_challenge,
)

PRODUCTION_REDIRECT_URL = "https://ai.youdoogo.com/api/v1/auth/feishu/callback"
CALLBACK_PATH = "/api/v1/auth/feishu/callback"
STATE_TTL_SECONDS = 600
EXCHANGE_TTL_SECONDS = 60
_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9_-]+$")
_VISIBLE_OAUTH_VALUE = re.compile(r"^[\x21-\x7e]+$")
_HEX_DIGEST = re.compile(r"^[0-9a-f]{64}$")


class OAuthUnavailable(Exception):
    """OAuth is disabled, misconfigured, or its state store is unavailable."""


class InvalidOAuthState(Exception):
    """OAuth state is absent, expired, replayed, tampered with, or unbound."""


class InvalidReturnTo(Exception):
    """A return path is not a same-origin local application path."""


class InvalidOAuthCallback(Exception):
    """The callback does not contain a valid authorization code."""


class OAuthProvider(Protocol):
    """Methods used from the focused Feishu user OAuth client."""

    def authorization_url(self, state: str, code_challenge: str) -> str: ...

    async def identity_from_code(
        self, code: str, code_verifier: str
    ) -> FeishuIdentity: ...


@dataclass(frozen=True)
class OAuthStateData:
    """Server-side transaction data protected by Redis TTL and atomic consume."""

    binding_digest: str
    code_verifier: str
    return_to: str


@dataclass(frozen=True)
class OAuthExchangeData:
    """Short-lived application JWT handoff data."""

    access_token: str
    token_type: str
    expires_in: int
    redirect_to: str


@dataclass(frozen=True)
class OAuthStart:
    authorization_url: str
    browser_binding: str
    secure_cookies: bool


@dataclass(frozen=True)
class OAuthCompletion:
    identity: FeishuIdentity
    return_to: str


class OAuthStore(Protocol):
    async def save_state(self, state_digest: str, data: OAuthStateData, ttl: int) -> bool: ...

    async def consume_state(
        self, state_digest: str, binding_digest: str
    ) -> OAuthStateData | None: ...

    async def save_exchange(
        self, handle_digest: str, data: OAuthExchangeData, ttl: int
    ) -> bool: ...

    async def consume_exchange(self, handle_digest: str) -> OAuthExchangeData | None: ...

    async def close(self) -> None: ...


class RedisOAuthStore:
    """Redis-backed, multi-worker-safe OAuth state and exchange storage."""

    _CONSUME_STATE = """
local value = redis.call('GET', KEYS[1])
if not value then return nil end
local ok, payload = pcall(cjson.decode, value)
if not ok or type(payload) ~= 'table' then
  redis.call('DEL', KEYS[1])
  return nil
end
if payload.binding_digest ~= ARGV[1] then return nil end
redis.call('DEL', KEYS[1])
return value
"""
    _CONSUME_VALUE = """
local value = redis.call('GET', KEYS[1])
if not value then return nil end
redis.call('DEL', KEYS[1])
return value
"""

    def __init__(self, redis_url: str) -> None:
        self.redis_url = redis_url
        self._client: aioredis.Redis | None = None

    def _get_client(self) -> aioredis.Redis:
        if self._client is None:
            self._client = aioredis.from_url(self.redis_url, decode_responses=True)
        return self._client

    async def save_state(self, state_digest: str, data: OAuthStateData, ttl: int) -> bool:
        try:
            result = await self._get_client().set(
                f"youdoo:feishu:state:{state_digest}",
                json.dumps(asdict(data), separators=(",", ":")),
                ex=ttl,
                nx=True,
            )
        except RedisError as exc:
            raise OAuthUnavailable from exc
        return bool(result)

    async def consume_state(
        self, state_digest: str, binding_digest: str
    ) -> OAuthStateData | None:
        try:
            raw = await self._get_client().eval(
                self._CONSUME_STATE,
                1,
                f"youdoo:feishu:state:{state_digest}",
                binding_digest,
            )
        except RedisError as exc:
            raise OAuthUnavailable from exc
        if not isinstance(raw, str):
            return None
        try:
            payload: Any = json.loads(raw)
            if not isinstance(payload, dict):
                return None
            saved_binding_digest = payload.get("binding_digest")
            code_verifier = payload.get("code_verifier")
            return_to = payload.get("return_to")
            if (
                not isinstance(saved_binding_digest, str)
                or _HEX_DIGEST.fullmatch(saved_binding_digest) is None
                or not isinstance(code_verifier, str)
                or not 43 <= len(code_verifier) <= 128
                or _SAFE_TOKEN.fullmatch(code_verifier) is None
                or not isinstance(return_to, str)
            ):
                return None
            return OAuthStateData(
                binding_digest=saved_binding_digest,
                code_verifier=code_verifier,
                return_to=normalize_return_to(return_to),
            )
        except (InvalidReturnTo, TypeError, ValueError):
            return None

    async def save_exchange(
        self, handle_digest: str, data: OAuthExchangeData, ttl: int
    ) -> bool:
        try:
            result = await self._get_client().set(
                f"youdoo:feishu:exchange:{handle_digest}",
                json.dumps(asdict(data), separators=(",", ":")),
                ex=ttl,
                nx=True,
            )
        except RedisError as exc:
            raise OAuthUnavailable from exc
        return bool(result)

    async def consume_exchange(self, handle_digest: str) -> OAuthExchangeData | None:
        try:
            raw = await self._get_client().eval(
                self._CONSUME_VALUE,
                1,
                f"youdoo:feishu:exchange:{handle_digest}",
            )
        except RedisError as exc:
            raise OAuthUnavailable from exc
        if not isinstance(raw, str):
            return None
        try:
            payload: Any = json.loads(raw)
            if not isinstance(payload, dict):
                return None
            access_token = payload.get("access_token")
            token_type = payload.get("token_type")
            expires_in = payload.get("expires_in")
            redirect_to = payload.get("redirect_to")
            if (
                not isinstance(access_token, str)
                or not 1 <= len(access_token) <= 8192
                or not isinstance(token_type, str)
                or not 1 <= len(token_type) <= 32
                or not isinstance(expires_in, int)
                or not 1 <= expires_in <= 31_536_000
                or not isinstance(redirect_to, str)
            ):
                return None
            return OAuthExchangeData(
                access_token=access_token,
                token_type=token_type,
                expires_in=expires_in,
                redirect_to=normalize_return_to(redirect_to),
            )
        except (InvalidReturnTo, TypeError, ValueError):
            return None

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


def load_oauth_config() -> FeishuOAuthConfig:
    """Load and validate OAuth configuration without affecting app startup."""
    settings = get_settings()
    if not _as_bool(runtime_config.effective("feishu_oauth_enabled", False)):
        raise OAuthUnavailable
    app_id = str(runtime_config.effective("feishu_app_id", "") or "")
    app_secret = str(runtime_config.effective("feishu_app_secret", "") or "")
    redirect_url = str(runtime_config.effective("feishu_redirect_url", "") or "")
    if (
        not 1 <= len(app_id) <= 128
        or _VISIBLE_OAUTH_VALUE.fullmatch(app_id) is None
        or not 1 <= len(app_secret) <= 512
        or _VISIBLE_OAUTH_VALUE.fullmatch(app_secret) is None
    ):
        raise OAuthUnavailable

    try:
        parsed = urlsplit(redirect_url)
    except ValueError as exc:
        raise OAuthUnavailable from exc
    if (
        parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path != CALLBACK_PATH
    ):
        raise OAuthUnavailable
    if settings.app_env != "local":
        if redirect_url != PRODUCTION_REDIRECT_URL:
            raise OAuthUnavailable
    else:
        local_http = parsed.scheme == "http" and parsed.hostname in {
            "localhost", "127.0.0.1", "test"
        }
        if parsed.scheme != "https" and not local_http:
            raise OAuthUnavailable
    if not parsed.hostname:
        raise OAuthUnavailable
    try:
        _ = parsed.port
    except ValueError as exc:
        raise OAuthUnavailable from exc
    return FeishuOAuthConfig(
        app_id=app_id,
        app_secret=app_secret,
        redirect_url=redirect_url,
        secure_cookies=parsed.scheme == "https",
    )


def normalize_return_to(raw: str | None) -> str:
    """Accept only local absolute paths; reject external, scheme-relative, and control input."""
    if raw is None or raw == "":
        return "/"
    if len(raw) > 2048:
        raise InvalidReturnTo
    decoded = unquote(raw)
    if any(ord(char) < 32 for char in decoded) or "\\" in decoded:
        raise InvalidReturnTo
    try:
        parsed = urlsplit(raw)
    except ValueError as exc:
        raise InvalidReturnTo from exc
    decoded_path = unquote(parsed.path)
    if (
        parsed.scheme
        or parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or not decoded_path.startswith("/")
        or decoded_path.startswith("//")
    ):
        raise InvalidReturnTo
    return parsed.geturl()


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class FeishuLoginService:
    """Coordinates state, PKCE, Feishu identity, and one-time JWT handoff."""

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
                binding_digest=_digest(browser_binding),
                code_verifier=code_verifier,
                return_to=safe_return_to,
            )
            if await self.store.save_state(_digest(state), data, STATE_TTL_SECONDS):
                provider = self.client_factory(config)
                return OAuthStart(
                    authorization_url=provider.authorization_url(
                        state, pkce_challenge(code_verifier)
                    ),
                    browser_binding=browser_binding,
                    secure_cookies=config.secure_cookies,
                )
        raise OAuthUnavailable

    async def consume_callback_state(self, state: str, browser_binding: str) -> OAuthStateData:
        if (
            not state
            or len(state) > 256
            or _SAFE_TOKEN.fullmatch(state) is None
            or not browser_binding
            or len(browser_binding) > 256
            or _SAFE_TOKEN.fullmatch(browser_binding) is None
        ):
            raise InvalidOAuthState
        binding_digest = _digest(browser_binding)
        data = await self.store.consume_state(_digest(state), binding_digest)
        if data is None or not secrets.compare_digest(data.binding_digest, binding_digest):
            raise InvalidOAuthState
        return data

    async def exchange_code(self, transaction: OAuthStateData, code: str) -> OAuthCompletion:
        if (
            not code
            or len(code) > 512
            or _VISIBLE_OAUTH_VALUE.fullmatch(code) is None
        ):
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
            if await self.store.save_exchange(_digest(handle), data, EXCHANGE_TTL_SECONDS):
                return handle, config.secure_cookies
        raise OAuthUnavailable

    async def consume_exchange(self, handle: str) -> OAuthExchangeData:
        if (
            not handle
            or len(handle) > 256
            or _SAFE_TOKEN.fullmatch(handle) is None
        ):
            raise InvalidOAuthState
        data = await self.store.consume_exchange(_digest(handle))
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
    """FastAPI dependency and process-level OAuth service singleton."""
    return feishu_login_service
