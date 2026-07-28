"""Stable error categories for internal service-token callers and adapters."""


class ServiceIdentityError(Exception):
    """Base class for all internal service identity failures."""


class ServiceIdentityConfigurationError(ServiceIdentityError):
    """Signing or verification configuration is absent or unsafe."""


class ServiceIdentitySigningError(ServiceIdentityError):
    """A token could not be signed with the configured private key."""


class ServiceIdentityVerificationError(ServiceIdentityError):
    """A token cannot be trusted by the receiving service."""


class ServiceIdentityTokenExpired(ServiceIdentityVerificationError):
    """The token is past its expiration time."""


class ServiceIdentityAudienceMismatch(ServiceIdentityVerificationError):
    """The token was issued for another receiving service."""


class ServiceIdentityIssuerMismatch(ServiceIdentityVerificationError):
    """The token came from an unexpected trust domain."""


class ServiceIdentitySignatureInvalid(ServiceIdentityVerificationError):
    """The token signature does not match the configured public key."""


class ServiceIdentityMissingClaim(ServiceIdentityVerificationError):
    """The token omits a claim required by the internal contract."""


class ServiceIdentityScopeDenied(ServiceIdentityVerificationError):
    """The token does not grant every scope required by the operation."""


class ServiceIdentityLifetimeInvalid(ServiceIdentityVerificationError):
    """The token lifetime is invalid or exceeds the internal maximum."""


class ServiceIdentityTokenMalformed(ServiceIdentityVerificationError):
    """The token cannot be decoded into the internal claims contract."""
