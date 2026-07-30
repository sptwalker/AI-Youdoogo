"""Fail-closed online session and entitlement confirmation from Lodge."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

import httpx

from app.platform.lodge_identity.claims import LodgePrincipal
from app.platform.lodge_identity.errors import LodgeIdentityConfigurationError, LodgeStatusDenied


class LodgeStatusClient:
    """Checks only the verified identity facts; no browser token or client role is forwarded."""

    def __init__(
        self,
        *,
        url: str,
        service_token: str,
        http_client: httpx.AsyncClient,
        timeout_seconds: float = 3.0,
        cache_ttl_seconds: int = 60,
        cache_max_entries: int = 10_000,
        max_response_bytes: int = 65_536,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not url.startswith("https://"):
            raise LodgeIdentityConfigurationError("LODGE_STATUS_URL must use HTTPS")
        if not service_token.strip():
            raise LodgeIdentityConfigurationError("LODGE_STATUS_SERVICE_TOKEN is required")
        if (
            timeout_seconds <= 0
            or cache_ttl_seconds < 1
            or cache_max_entries < 1
            or max_response_bytes < 1
        ):
            raise LodgeIdentityConfigurationError("invalid Lodge status client limits")
        self._url = url
        self._service_token = service_token.strip()
        self._http_client = http_client
        self._timeout_seconds = timeout_seconds
        self._cache_ttl_seconds = cache_ttl_seconds
        self._cache_max_entries = cache_max_entries
        self._max_response_bytes = max_response_bytes
        self._clock = clock
        self._cache: dict[tuple[str, str, str, int, str], float] = {}

    async def require_active(self, principal: LodgePrincipal) -> None:
        cache_key = (
            principal.subject,
            principal.session_id,
            principal.organization_id,
            principal.identity_version,
            principal.token_id,
        )
        now = self._clock()
        self._discard_expired(now)
        if self._cache.get(cache_key, 0.0) > now:
            return
        try:
            async with self._http_client.stream(
                "POST",
                self._url,
                json={
                    "system_key": "youdoogo",
                    "subject": principal.subject,
                    "identity_ver": principal.identity_version,
                    "sid": principal.session_id,
                    "jti": principal.token_id,
                    "audience": "youdoogo",
                    "org_id": principal.organization_id,
                },
                timeout=self._timeout_seconds,
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {self._service_token}",
                },
            ) as response:
                response.raise_for_status()
                body = await self._read_bounded(response)
            payload = json.loads(body)
            self._assert_matches(payload, principal)
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise LodgeStatusDenied("Lodge identity status cannot affirm this session") from exc
        now = self._clock()
        self._discard_expired(now)
        self._cache[cache_key] = now + self._cache_ttl_seconds
        self._enforce_capacity()

    def _discard_expired(self, now: float) -> None:
        expired = [cache_key for cache_key, expires_at in self._cache.items() if expires_at <= now]
        for cache_key in expired:
            del self._cache[cache_key]

    def _enforce_capacity(self) -> None:
        while len(self._cache) > self._cache_max_entries:
            cache_key, _ = min(self._cache.items(), key=lambda item: (item[1], item[0]))
            del self._cache[cache_key]

    def _assert_matches(self, payload: Any, principal: LodgePrincipal) -> None:
        if not isinstance(payload, dict):
            raise ValueError("status is not an object")
        entitlement = payload["entitlement"]
        current_identity_version = payload["current_identity_ver"]
        checked_at = payload["checked_at"]
        scopes = payload["scopes"]
        if (
            payload["active"] is not True
            or payload["subject"] != principal.subject
            or payload["sid"] != principal.session_id
            or payload["jti"] != principal.token_id
            or payload["system_key"] != "youdoogo"
            or payload["audience"] != "youdoogo"
            or payload["org_id"] != principal.organization_id
            or isinstance(current_identity_version, bool)
            or not isinstance(current_identity_version, int)
            or current_identity_version != principal.identity_version
            or payload["session_active"] is not True
            or not isinstance(entitlement, dict)
            or entitlement.get("allowed") is not True
            or not isinstance(checked_at, str)
            or not checked_at.strip()
            or not isinstance(scopes, list)
            or any(not isinstance(scope, str) or not scope for scope in scopes)
        ):
            raise ValueError("status does not match verified token")

    async def _read_bounded(self, response: httpx.Response) -> bytes:
        chunks: list[bytes] = []
        size = 0
        async for chunk in response.aiter_bytes():
            size += len(chunk)
            if size > self._max_response_bytes:
                raise ValueError("status response exceeds configured limit")
            chunks.append(chunk)
        return b"".join(chunks)
