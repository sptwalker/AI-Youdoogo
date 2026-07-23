"""Transient, single-use Feishu OAuth state and exchange token storage."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, Protocol

import redis.asyncio as aioredis
from redis.exceptions import RedisError

from .oauth_config import (
    HEX_DIGEST,
    SAFE_TOKEN,
    InvalidReturnTo,
    OAuthUnavailable,
    normalize_return_to,
)

STATE_TTL_SECONDS = 600
EXCHANGE_TTL_SECONDS = 60


@dataclass(frozen=True)
class OAuthStateData:
    binding_digest: str
    code_verifier: str
    return_to: str


@dataclass(frozen=True)
class OAuthExchangeData:
    access_token: str
    token_type: str
    expires_in: int
    redirect_to: str


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
                or HEX_DIGEST.fullmatch(saved_binding_digest) is None
                or not isinstance(code_verifier, str)
                or not 43 <= len(code_verifier) <= 128
                or SAFE_TOKEN.fullmatch(code_verifier) is None
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
