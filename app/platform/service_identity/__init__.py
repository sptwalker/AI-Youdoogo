"""Dormant internal service identity primitives; not the user authentication API."""

from app.platform.service_identity.contracts import ServiceIdentityClaims
from app.platform.service_identity.errors import (
    ServiceIdentityAudienceMismatch,
    ServiceIdentityConfigurationError,
    ServiceIdentityError,
    ServiceIdentityIssuerMismatch,
    ServiceIdentityLifetimeInvalid,
    ServiceIdentityMissingClaim,
    ServiceIdentityScopeDenied,
    ServiceIdentitySignatureInvalid,
    ServiceIdentitySigningError,
    ServiceIdentityTokenExpired,
    ServiceIdentityTokenMalformed,
    ServiceIdentityVerificationError,
)
from app.platform.service_identity.jwt import (
    MAX_TOKEN_TTL_SECONDS,
    ServiceTokenIssuer,
    ServiceTokenVerifier,
    issuer_from_settings,
    verifier_from_settings,
)

__all__ = [
    "MAX_TOKEN_TTL_SECONDS",
    "ServiceIdentityAudienceMismatch",
    "ServiceIdentityClaims",
    "ServiceIdentityConfigurationError",
    "ServiceIdentityError",
    "ServiceIdentityIssuerMismatch",
    "ServiceIdentityLifetimeInvalid",
    "ServiceIdentityMissingClaim",
    "ServiceIdentityScopeDenied",
    "ServiceIdentitySignatureInvalid",
    "ServiceIdentitySigningError",
    "ServiceIdentityTokenExpired",
    "ServiceIdentityTokenMalformed",
    "ServiceIdentityVerificationError",
    "ServiceTokenIssuer",
    "ServiceTokenVerifier",
    "issuer_from_settings",
    "verifier_from_settings",
]
