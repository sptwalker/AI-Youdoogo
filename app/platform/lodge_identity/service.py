"""Optional, isolated Lodge resource-server service."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx
import jwt

from app.core.config import Settings
from app.platform.lodge_identity.claims import LodgePrincipal
from app.platform.lodge_identity.errors import LodgeIdentityConfigurationError, LodgeTokenRejected
from app.platform.lodge_identity.jwks import LodgeJwksClient
from app.platform.lodge_identity.status import LodgeStatusClient

_REQUIRED_CLAIMS = (
    "contract_ver",
    "token_use",
    "token_profile",
    "iss",
    "aud",
    "sub",
    "sid",
    "org_id",
    "identity_ver",
    "jti",
    "iat",
    "nbf",
    "exp",
    "entitlements",
    "scope",
)
_MAX_TOKEN_TTL_SECONDS = 900
_SCOPE_CEILINGS = {
    "viewer": frozenset({"decision:read"}),
    "editor": frozenset(
        {"decision:read", "decision:proposal:draft", "decision:proposal:submit"}
    ),
    "system_admin": frozenset(
        {
            "decision:read",
            "decision:proposal:draft",
            "decision:proposal:submit",
            "decision:config:read",
            "decision:config:write",
        }
    ),
}
_FORBIDDEN_SCOPES = frozenset(
    {"decision:proposal:approve", "decision:proposal:reject", "decision:proposal:publish"}
)


class LodgeIdentityService:
    """Verifies the exact Lodge user-target contract before online status confirmation."""

    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        jwks_url: str,
        status_url: str,
        status_service_token: str,
        http_client: httpx.AsyncClient,
        timeout_seconds: float = 3.0,
        jwks_cache_ttl_seconds: int = 300,
        status_cache_ttl_seconds: int = 60,
        status_cache_max_entries: int = 10_000,
        max_response_bytes: int = 65_536,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if not issuer.startswith("https://"):
            raise LodgeIdentityConfigurationError("LODGE_ISSUER must use HTTPS")
        if audience != "youdoogo":
            raise LodgeIdentityConfigurationError("LODGE_AUDIENCE must be exactly youdoogo")
        self._issuer = issuer.rstrip("/")
        self._audience = audience
        self._now = now
        self._jwks = LodgeJwksClient(
            url=jwks_url,
            http_client=http_client,
            timeout_seconds=timeout_seconds,
            cache_ttl_seconds=jwks_cache_ttl_seconds,
            max_response_bytes=max_response_bytes,
        )
        self._status = LodgeStatusClient(
            url=status_url,
            service_token=status_service_token,
            http_client=http_client,
            timeout_seconds=timeout_seconds,
            cache_ttl_seconds=status_cache_ttl_seconds,
            cache_max_entries=status_cache_max_entries,
            max_response_bytes=max_response_bytes,
        )

    async def authenticate(self, token: str) -> LodgePrincipal:
        header = self._header(token)
        key = await self._jwks.key_for(header["kid"])
        try:
            payload = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                issuer=self._issuer,
                audience=self._audience,
                options={
                    "require": list(_REQUIRED_CLAIMS),
                    "verify_exp": False,
                    "verify_iat": False,
                    "verify_nbf": False,
                },
            )
        except jwt.ExpiredSignatureError as exc:
            raise LodgeTokenRejected("Lodge token expired") from exc
        except jwt.ImmatureSignatureError as exc:
            raise LodgeTokenRejected("Lodge token is not yet valid") from exc
        except jwt.InvalidAudienceError as exc:
            raise LodgeTokenRejected("Lodge token audience is invalid") from exc
        except jwt.MissingRequiredClaimError as exc:
            if exc.claim == "contract_ver":
                raise LodgeTokenRejected("Lodge token contract_ver is required") from exc
            raise LodgeTokenRejected(
                "Lodge token signature or required claims are malformed"
            ) from exc
        except jwt.InvalidTokenError as exc:
            raise LodgeTokenRejected(
                "Lodge token signature or required claims are malformed"
            ) from exc
        try:
            issued_at = _int(payload, "iat")
            expires_at = _int(payload, "exp")
            not_before = _int(payload, "nbf")
        except (KeyError, TypeError) as exc:
            raise LodgeTokenRejected("Lodge token time claims are malformed") from exc
        now_timestamp = self._now().timestamp()
        if issued_at > now_timestamp:
            raise LodgeTokenRejected("Lodge token issued-at time is invalid")
        if expires_at <= now_timestamp:
            raise LodgeTokenRejected("Lodge token expired")
        if not_before > now_timestamp:
            raise LodgeTokenRejected("Lodge token is not yet valid")
        if expires_at - issued_at > _MAX_TOKEN_TTL_SECONDS:
            raise LodgeTokenRejected("Lodge token TTL exceeds the contract maximum")
        principal = self._principal(payload)
        await self._status.require_active(principal)
        return principal

    def _header(self, token: str) -> dict[str, str]:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.InvalidTokenError as exc:
            raise LodgeTokenRejected("Lodge token header is malformed") from exc
        if header.get("alg") != "RS256":
            raise LodgeTokenRejected("Lodge token algorithm must be RS256")
        if header.get("typ") != "at+jwt":
            raise LodgeTokenRejected("Lodge token typ must be at+jwt")
        kid = header.get("kid")
        if not isinstance(kid, str) or not kid.strip():
            raise LodgeTokenRejected("Lodge token kid is missing")
        return {"kid": kid}

    def _principal(self, payload: dict[str, Any]) -> LodgePrincipal:
        if payload.get("aud") != [self._audience]:
            raise LodgeTokenRejected("Lodge token audience must be exactly youdoogo")
        if payload.get("token_use") != "access":
            raise LodgeTokenRejected("Lodge token token_use must be access")
        if payload.get("token_profile") != "user":
            raise LodgeTokenRejected("Lodge token token_profile must be user")
        if payload.get("contract_ver") != "lodge_identity_v2":
            raise LodgeTokenRejected("Lodge token contract_ver must be lodge_identity_v2")
        try:
            self._validate_entitlements_and_scopes(payload)
            identity_version = _int(payload, "identity_ver")
            if identity_version <= 0:
                raise TypeError("identity_ver")
            return LodgePrincipal(
                subject=_text(payload, "sub"),
                session_id=_text(payload, "sid"),
                organization_id=_text(payload, "org_id"),
                identity_version=identity_version,
                token_id=_text(payload, "jti"),
                issued_at=datetime.fromtimestamp(_int(payload, "iat"), tz=UTC),
                expires_at=datetime.fromtimestamp(_int(payload, "exp"), tz=UTC),
            )
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise LodgeTokenRejected("Lodge token required claims are malformed") from exc

    def _validate_entitlements_and_scopes(self, payload: dict[str, Any]) -> None:
        entitlements = payload["entitlements"]
        if not isinstance(entitlements, dict):
            raise TypeError("entitlements")
        entitlement = entitlements["youdoogo"]
        if not isinstance(entitlement, dict) or entitlement.get("allowed") is not True:
            raise TypeError("entitlements.youdoogo")
        system_role = _text(entitlement, "system_role")
        _text(entitlement, "source")
        ceiling = _SCOPE_CEILINGS.get(system_role)
        if ceiling is None:
            raise TypeError("system_role")
        self._validate_scopes(entitlement["scopes"], ceiling)
        self._validate_scopes(payload["scope"], ceiling)

    @staticmethod
    def _validate_scopes(value: Any, ceiling: frozenset[str]) -> None:
        if not isinstance(value, list) or any(
            not isinstance(scope, str) or not scope for scope in value
        ):
            raise TypeError("scope")
        scopes = frozenset(value)
        if not scopes <= ceiling or not scopes.isdisjoint(_FORBIDDEN_SCOPES):
            raise TypeError("scope")


def _text(payload: dict[str, Any], field: str) -> str:
    value = payload[field]
    if not isinstance(value, str) or not value.strip():
        raise TypeError(field)
    return value.strip()


def _int(payload: dict[str, Any], field: str) -> int:
    value = payload[field]
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(field)
    return value


def service_from_settings(
    settings: Settings, http_client: httpx.AsyncClient | None = None
) -> LodgeIdentityService:
    """Construct only when Lodge is explicitly enabled; never alters legacy authentication."""
    if not settings.lodge_identity_enabled:
        raise LodgeIdentityConfigurationError("Lodge identity is disabled")
    if http_client is None:
        raise LodgeIdentityConfigurationError("an explicit HTTP client is required")
    return LodgeIdentityService(
        issuer=settings.lodge_issuer,
        audience=settings.lodge_audience,
        jwks_url=settings.lodge_jwks_url,
        status_url=settings.lodge_status_url,
        status_service_token=settings.lodge_status_service_token.get_secret_value(),
        http_client=http_client,
        timeout_seconds=settings.lodge_http_timeout_seconds,
        jwks_cache_ttl_seconds=settings.lodge_jwks_cache_ttl_seconds,
        status_cache_ttl_seconds=settings.lodge_status_cache_ttl_seconds,
        status_cache_max_entries=settings.lodge_status_cache_max_entries,
        max_response_bytes=settings.lodge_response_max_bytes,
    )
