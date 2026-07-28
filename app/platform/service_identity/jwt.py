"""RS256 short-lived JWT mechanism for service-to-service authentication.

This module is deliberately independent from the existing user-facing HS256 JWT. It is
not wired into HTTP routes yet; callers must opt in through an explicit issuer/verifier.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey

from app.core.config import Settings, get_settings
from app.platform.service_identity.contracts import ServiceIdentityClaims
from app.platform.service_identity.errors import (
    ServiceIdentityAudienceMismatch,
    ServiceIdentityConfigurationError,
    ServiceIdentityIssuerMismatch,
    ServiceIdentityLifetimeInvalid,
    ServiceIdentityMissingClaim,
    ServiceIdentityScopeDenied,
    ServiceIdentitySignatureInvalid,
    ServiceIdentitySigningError,
    ServiceIdentityTokenExpired,
    ServiceIdentityTokenMalformed,
)

ALGORITHM = "RS256"
MAX_TOKEN_TTL_SECONDS = 300
_REQUIRED_CLAIMS = ("iss", "aud", "service_id", "actor", "scope", "iat", "exp", "jti")


def _required_text(value: str, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ServiceIdentityConfigurationError(f"{field} must not be empty")
    return normalized


def _normalize_scope(scopes: Iterable[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    for raw_scope in scopes:
        scope = raw_scope.strip()
        if not scope or any(character.isspace() for character in scope):
            raise ServiceIdentityConfigurationError(
                "scope entries must be non-empty and contain no whitespace"
            )
        if scope not in normalized:
            normalized.append(scope)
    if not normalized:
        raise ServiceIdentityConfigurationError("at least one scope is required")
    return tuple(normalized)


def _pem_bytes(value: str) -> bytes:
    """Normalize PEM supplied by an env var, including escaped line breaks."""
    normalized = value.strip()
    if "\\n" in normalized and "\n" not in normalized:
        normalized = normalized.replace("\\n", "\n")
    return normalized.encode("utf-8")


def _load_private_key(value: str) -> RSAPrivateKey:
    try:
        key = serialization.load_pem_private_key(_pem_bytes(value), password=None)
    except (TypeError, ValueError) as exc:
        raise ServiceIdentityConfigurationError("invalid INTERNAL_JWT_PRIVATE_KEY PEM") from exc
    if not isinstance(key, RSAPrivateKey):
        raise ServiceIdentityConfigurationError("INTERNAL_JWT_PRIVATE_KEY must be an RSA key")
    if key.key_size < 2048:
        raise ServiceIdentityConfigurationError(
            "INTERNAL_JWT_PRIVATE_KEY must be at least 2048 bits"
        )
    return key


def _load_public_key(value: str) -> RSAPublicKey:
    try:
        key = serialization.load_pem_public_key(_pem_bytes(value))
    except (TypeError, ValueError) as exc:
        raise ServiceIdentityConfigurationError("invalid INTERNAL_JWT_PUBLIC_KEY PEM") from exc
    if not isinstance(key, RSAPublicKey):
        raise ServiceIdentityConfigurationError("INTERNAL_JWT_PUBLIC_KEY must be an RSA key")
    if key.key_size < 2048:
        raise ServiceIdentityConfigurationError(
            "INTERNAL_JWT_PUBLIC_KEY must be at least 2048 bits"
        )
    return key


def _validated_ttl(ttl_seconds: int) -> int:
    if ttl_seconds < 1 or ttl_seconds > MAX_TOKEN_TTL_SECONDS:
        raise ServiceIdentityConfigurationError(
            f"internal token TTL must be between 1 and {MAX_TOKEN_TTL_SECONDS} seconds"
        )
    return ttl_seconds


class ServiceTokenIssuer:
    """Issue audience-bound tokens from a configured RSA private key."""

    def __init__(
        self,
        *,
        private_key: str,
        issuer: str,
        audience: str,
        service_id: str,
        ttl_seconds: int = MAX_TOKEN_TTL_SECONDS,
    ) -> None:
        self._private_key = _load_private_key(private_key)
        self._issuer = _required_text(issuer, "issuer")
        self._audience = _required_text(audience, "audience")
        self._service_id = _required_text(service_id, "service_id")
        self._ttl_seconds = _validated_ttl(ttl_seconds)

    def issue(
        self,
        *,
        actor: str,
        scope: Iterable[str],
        audience: str | None = None,
        now: datetime | None = None,
        jti: str | None = None,
    ) -> str:
        """Sign a short-lived token without consulting user-JWT configuration."""
        issued_at = now or datetime.now(UTC)
        if issued_at.tzinfo is None:
            raise ServiceIdentityConfigurationError("now must be timezone-aware")
        resolved_actor = _required_text(actor, "actor")
        resolved_audience = _required_text(audience or self._audience, "audience")
        resolved_scope = _normalize_scope(scope)
        resolved_jti = _required_text(jti or str(uuid.uuid4()), "jti")
        payload = {
            "iss": self._issuer,
            "aud": resolved_audience,
            "service_id": self._service_id,
            "actor": resolved_actor,
            "scope": " ".join(resolved_scope),
            "iat": issued_at,
            "exp": issued_at + timedelta(seconds=self._ttl_seconds),
            "jti": resolved_jti,
        }
        try:
            return jwt.encode(payload, self._private_key, algorithm=ALGORITHM)
        except jwt.PyJWTError as exc:
            raise ServiceIdentitySigningError("failed to sign internal service token") from exc


class ServiceTokenVerifier:
    """Verify signature, trust domain, audience, lifetime, and required scopes."""

    def __init__(
        self,
        *,
        public_key: str,
        issuer: str,
        audience: str,
        max_ttl_seconds: int = MAX_TOKEN_TTL_SECONDS,
        leeway_seconds: int = 10,
    ) -> None:
        self._public_key = _load_public_key(public_key)
        self._issuer = _required_text(issuer, "issuer")
        self._audience = _required_text(audience, "audience")
        self._max_ttl_seconds = _validated_ttl(max_ttl_seconds)
        if leeway_seconds < 0:
            raise ServiceIdentityConfigurationError("leeway_seconds must not be negative")
        self._leeway_seconds = leeway_seconds

    def verify(
        self,
        token: str,
        *,
        required_scopes: Iterable[str] = (),
    ) -> ServiceIdentityClaims:
        """Return typed claims or raise a stable, actionable error category."""
        try:
            payload = jwt.decode(
                token,
                self._public_key,
                algorithms=[ALGORITHM],
                issuer=self._issuer,
                audience=self._audience,
                leeway=self._leeway_seconds,
                options={"require": list(_REQUIRED_CLAIMS)},
            )
        except jwt.ExpiredSignatureError as exc:
            raise ServiceIdentityTokenExpired("internal service token has expired") from exc
        except jwt.InvalidAudienceError as exc:
            raise ServiceIdentityAudienceMismatch(
                "internal service token audience mismatch"
            ) from exc
        except jwt.InvalidIssuerError as exc:
            raise ServiceIdentityIssuerMismatch("internal service token issuer mismatch") from exc
        except jwt.MissingRequiredClaimError as exc:
            raise ServiceIdentityMissingClaim(f"internal token missing claim: {exc.claim}") from exc
        except jwt.InvalidSignatureError as exc:
            raise ServiceIdentitySignatureInvalid(
                "internal service token signature invalid"
            ) from exc
        except jwt.InvalidTokenError as exc:
            raise ServiceIdentityTokenMalformed("internal service token is malformed") from exc

        claims = self._to_claims(payload)
        normalized_required = _normalize_optional_scopes(required_scopes)
        if not claims.permits(normalized_required):
            raise ServiceIdentityScopeDenied("internal service token lacks a required scope")
        return claims

    def _to_claims(self, payload: dict[str, Any]) -> ServiceIdentityClaims:
        try:
            issuer = _payload_text(payload, "iss")
            audience = _payload_audience(payload)
            service_id = _payload_text(payload, "service_id")
            actor = _payload_text(payload, "actor")
            token_scope = _payload_scope(payload)
            issued_at = datetime.fromtimestamp(_payload_int(payload, "iat"), tz=UTC)
            expires_at = datetime.fromtimestamp(_payload_int(payload, "exp"), tz=UTC)
            jti = _payload_text(payload, "jti")
        except (TypeError, ValueError, OverflowError) as exc:
            raise ServiceIdentityTokenMalformed("internal token claims are malformed") from exc
        lifetime_seconds = (expires_at - issued_at).total_seconds()
        if lifetime_seconds <= 0 or lifetime_seconds > self._max_ttl_seconds:
            raise ServiceIdentityLifetimeInvalid(
                "internal service token lifetime is invalid or too long"
            )
        return ServiceIdentityClaims(
            issuer=issuer,
            audience=audience,
            service_id=service_id,
            actor=actor,
            scope=token_scope,
            issued_at=issued_at,
            expires_at=expires_at,
            jti=jti,
        )


def _payload_text(payload: dict[str, Any], field: str) -> str:
    value = payload[field]
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be non-empty text")
    return value.strip()


def _payload_int(payload: dict[str, Any], field: str) -> int:
    value = payload[field]
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be an integer")
    return value


def _payload_audience(payload: dict[str, Any]) -> str:
    value = payload["aud"]
    if isinstance(value, str):
        return _required_payload_text(value, "aud")
    if isinstance(value, list) and len(value) == 1 and isinstance(value[0], str):
        return _required_payload_text(value[0], "aud")
    raise TypeError("aud must contain exactly one audience")


def _required_payload_text(value: str, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} must be non-empty text")
    return normalized


def _payload_scope(payload: dict[str, Any]) -> tuple[str, ...]:
    raw_scope = payload["scope"]
    if not isinstance(raw_scope, str):
        raise TypeError("scope must be a space-delimited string")
    normalized = _normalize_optional_scopes(raw_scope.split())
    if not normalized:
        raise ValueError("scope must contain at least one entry")
    return normalized


def _normalize_optional_scopes(scopes: Iterable[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    for raw_scope in scopes:
        scope = raw_scope.strip()
        if not scope or any(character.isspace() for character in scope):
            raise ServiceIdentityTokenMalformed("scope entries are malformed")
        if scope not in normalized:
            normalized.append(scope)
    return tuple(normalized)


def issuer_from_settings(settings: Settings | None = None) -> ServiceTokenIssuer:
    """Build an issuer only when the dormant internal identity feature is enabled."""
    configured = settings or get_settings()
    if not configured.internal_jwt_enabled:
        raise ServiceIdentityConfigurationError("internal service identity is disabled")
    return ServiceTokenIssuer(
        private_key=configured.internal_jwt_private_key,
        issuer=configured.internal_jwt_issuer,
        audience=configured.internal_jwt_audience,
        service_id=configured.internal_jwt_service_id,
        ttl_seconds=configured.internal_jwt_ttl_seconds,
    )


def verifier_from_settings(settings: Settings | None = None) -> ServiceTokenVerifier:
    """Build a verifier only when the dormant internal identity feature is enabled."""
    configured = settings or get_settings()
    if not configured.internal_jwt_enabled:
        raise ServiceIdentityConfigurationError("internal service identity is disabled")
    return ServiceTokenVerifier(
        public_key=configured.internal_jwt_public_key,
        issuer=configured.internal_jwt_issuer,
        audience=configured.internal_jwt_audience,
        max_ttl_seconds=configured.internal_jwt_ttl_seconds,
    )
