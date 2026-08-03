"""Bounded JWKS retrieval for the fixed Lodge issuer trust domain."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from typing import Any

import httpx
from jwt.algorithms import RSAAlgorithm

from app.platform.lodge_identity.errors import LodgeIdentityConfigurationError, LodgeTokenRejected


class LodgeJwksClient:
    """Cache RSA keys and allow one rate-limited refresh for an unknown key id."""

    def __init__(
        self,
        *,
        url: str,
        http_client: httpx.AsyncClient,
        timeout_seconds: float = 3.0,
        cache_ttl_seconds: int = 300,
        max_response_bytes: int = 65_536,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not url.startswith("https://"):
            raise LodgeIdentityConfigurationError("LODGE_JWKS_URL must use HTTPS")
        if timeout_seconds <= 0 or cache_ttl_seconds < 1 or max_response_bytes < 1:
            raise LodgeIdentityConfigurationError("invalid Lodge JWKS client limits")
        self._url = url
        self._http_client = http_client
        self._timeout_seconds = timeout_seconds
        self._cache_ttl_seconds = cache_ttl_seconds
        self._max_response_bytes = max_response_bytes
        self._clock = clock
        self._keys: dict[str, Any] = {}
        self._expires_at = 0.0
        self._unknown_kid_refresh_until = 0.0
        self._lock = asyncio.Lock()

    async def key_for(self, kid: str) -> Any:
        if not kid:
            raise LodgeTokenRejected("Lodge token kid is missing")
        async with self._lock:
            if self._expires_at <= self._clock():
                await self._refresh()
            key = self._keys.get(kid)
            if key is not None:
                return key
            if self._unknown_kid_refresh_until <= self._clock():
                self._unknown_kid_refresh_until = self._clock() + self._cache_ttl_seconds
                await self._refresh()
                key = self._keys.get(kid)
                if key is not None:
                    return key
            raise LodgeTokenRejected("Lodge token uses an unknown kid")

    async def _refresh(self) -> None:
        try:
            async with self._http_client.stream(
                "GET",
                self._url,
                timeout=self._timeout_seconds,
                headers={"Accept": "application/json"},
            ) as response:
                response.raise_for_status()
                body = await self._read_bounded(response)
        except (httpx.HTTPError, ValueError) as exc:
            raise LodgeTokenRejected("Lodge JWKS is unavailable") from exc
        try:
            document = json.loads(body)
            raw_keys = document["keys"]
            if not isinstance(raw_keys, list):
                raise TypeError("keys is not a list")
            keys = {
                raw["kid"]: RSAAlgorithm.from_jwk(json.dumps(raw))
                for raw in raw_keys
                if isinstance(raw, dict)
                and raw.get("kty") == "RSA"
                and raw.get("use", "sig") == "sig"
                and isinstance(raw.get("kid"), str)
            }
        except (KeyError, TypeError, ValueError) as exc:
            raise LodgeTokenRejected("Lodge JWKS response is malformed") from exc
        if not keys:
            raise LodgeTokenRejected("Lodge JWKS contains no signing keys")
        self._keys = keys
        self._expires_at = self._clock() + self._cache_ttl_seconds

    async def _read_bounded(self, response: httpx.Response) -> bytes:
        chunks: list[bytes] = []
        size = 0
        async for chunk in response.aiter_bytes():
            size += len(chunk)
            if size > self._max_response_bytes:
                raise ValueError("JWKS response exceeds configured limit")
            chunks.append(chunk)
        return b"".join(chunks)
