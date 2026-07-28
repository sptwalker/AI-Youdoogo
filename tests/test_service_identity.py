"""Internal service identity is asymmetric, short-lived, and separate from user JWT."""

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey

from app.core.config import Settings
from app.platform.service_identity import (
    ServiceIdentityAudienceMismatch,
    ServiceIdentityConfigurationError,
    ServiceIdentityIssuerMismatch,
    ServiceIdentityLifetimeInvalid,
    ServiceIdentityMissingClaim,
    ServiceIdentityScopeDenied,
    ServiceIdentitySignatureInvalid,
    ServiceIdentityTokenExpired,
    ServiceIdentityTokenMalformed,
    ServiceTokenIssuer,
    ServiceTokenVerifier,
    issuer_from_settings,
    verifier_from_settings,
)


@pytest.fixture
def rsa_key_pair() -> tuple[str, str]:
    """Generate ephemeral test keys; runtime code never generates or persists keys."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return private_pem, public_pem


def _issuer(private_key: str, **overrides: object) -> ServiceTokenIssuer:
    values: dict[str, object] = {
        "private_key": private_key,
        "issuer": "youdoo-internal",
        "audience": "knowledge-service",
        "service_id": "business-api",
        "ttl_seconds": 300,
    }
    values.update(overrides)
    return ServiceTokenIssuer(**values)  # type: ignore[arg-type]


def _verifier(public_key: str, **overrides: object) -> ServiceTokenVerifier:
    values: dict[str, object] = {
        "public_key": public_key,
        "issuer": "youdoo-internal",
        "audience": "knowledge-service",
        "max_ttl_seconds": 300,
        "leeway_seconds": 0,
    }
    values.update(overrides)
    return ServiceTokenVerifier(**values)  # type: ignore[arg-type]


def test_issue_and_verify_all_internal_claims(rsa_key_pair: tuple[str, str]) -> None:
    private_key, public_key = rsa_key_pair
    now = datetime.now(UTC).replace(microsecond=0)

    token = _issuer(private_key).issue(
        actor="user:42",
        scope=("knowledge:search", "knowledge:read", "knowledge:read"),
        now=now,
        jti="test-jti",
    )
    claims = _verifier(public_key).verify(token, required_scopes=("knowledge:read",))

    assert claims.issuer == "youdoo-internal"
    assert claims.audience == "knowledge-service"
    assert claims.service_id == "business-api"
    assert claims.actor == "user:42"
    assert claims.scope == ("knowledge:search", "knowledge:read")
    assert claims.issued_at == now
    assert claims.expires_at == now + timedelta(seconds=300)
    assert claims.jti == "test-jti"
    assert jwt.get_unverified_header(token)["alg"] == "RS256"


def test_factory_is_disabled_by_default_and_reads_only_configured_keys(
    rsa_key_pair: tuple[str, str],
) -> None:
    private_key, public_key = rsa_key_pair
    disabled = Settings(_env_file=None)  # type: ignore[call-arg]
    with pytest.raises(ServiceIdentityConfigurationError, match="disabled"):
        issuer_from_settings(disabled)

    enabled = Settings(
        internal_jwt_enabled=True,
        internal_jwt_issuer="youdoo-internal",
        internal_jwt_audience="knowledge-service",
        internal_jwt_service_id="business-api",
        internal_jwt_private_key=private_key,
        internal_jwt_public_key=public_key,
        internal_jwt_ttl_seconds=120,
        _env_file=None,
    )  # type: ignore[call-arg]
    token = issuer_from_settings(enabled).issue(actor="service:business", scope=("read",))
    assert verifier_from_settings(enabled).verify(token).service_id == "business-api"


def test_rejects_ttl_above_five_minutes(rsa_key_pair: tuple[str, str]) -> None:
    private_key, _ = rsa_key_pair
    with pytest.raises(ServiceIdentityConfigurationError, match="between 1 and 300"):
        _issuer(private_key, ttl_seconds=301)


def test_rejects_weak_rsa_keys() -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=1024)
    private_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public_pem = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()

    with pytest.raises(ServiceIdentityConfigurationError, match="at least 2048 bits"):
        _issuer(private_pem)
    with pytest.raises(ServiceIdentityConfigurationError, match="at least 2048 bits"):
        _verifier(public_pem)


def test_verification_errors_are_classified(rsa_key_pair: tuple[str, str]) -> None:
    private_key, public_key = rsa_key_pair
    token = _issuer(private_key).issue(actor="service:business", scope=("knowledge:read",))

    with pytest.raises(ServiceIdentityAudienceMismatch):
        _verifier(public_key, audience="expert-service").verify(token)
    with pytest.raises(ServiceIdentityIssuerMismatch):
        _verifier(public_key, issuer="another-trust-domain").verify(token)
    with pytest.raises(ServiceIdentityScopeDenied):
        _verifier(public_key).verify(token, required_scopes=("knowledge:write",))
    with pytest.raises(ServiceIdentityTokenMalformed):
        _verifier(public_key).verify("not-a-jwt")


def test_rejects_expired_and_wrongly_signed_tokens(
    rsa_key_pair: tuple[str, str],
) -> None:
    private_key, public_key = rsa_key_pair
    expired = _issuer(private_key, ttl_seconds=60).issue(
        actor="service:business",
        scope=("knowledge:read",),
        now=datetime.now(UTC) - timedelta(minutes=2),
    )
    with pytest.raises(ServiceIdentityTokenExpired):
        _verifier(public_key).verify(expired)

    another_private, _ = _generate_key_pair()
    wrong_signature = _issuer(another_private).issue(
        actor="service:business",
        scope=("knowledge:read",),
    )
    with pytest.raises(ServiceIdentitySignatureInvalid):
        _verifier(public_key).verify(wrong_signature)


def test_rejects_missing_claim_and_excessive_signed_lifetime(
    rsa_key_pair: tuple[str, str],
) -> None:
    private_key, public_key = rsa_key_pair
    now = datetime.now(UTC).replace(microsecond=0)
    base_payload = {
        "iss": "youdoo-internal",
        "aud": "knowledge-service",
        "service_id": "business-api",
        "actor": "service:business",
        "scope": "knowledge:read",
        "iat": now,
        "exp": now + timedelta(seconds=300),
        "jti": "manual-token",
    }
    private_object = serialization.load_pem_private_key(private_key.encode(), password=None)
    assert isinstance(private_object, RSAPrivateKey)

    missing_actor = dict(base_payload)
    missing_actor.pop("actor")
    token = jwt.encode(missing_actor, private_object, algorithm="RS256")
    with pytest.raises(ServiceIdentityMissingClaim, match="actor"):
        _verifier(public_key).verify(token)

    excessive = dict(base_payload)
    excessive["exp"] = now + timedelta(seconds=301)
    token = jwt.encode(excessive, private_object, algorithm="RS256")
    with pytest.raises(ServiceIdentityLifetimeInvalid):
        _verifier(public_key).verify(token)


def _generate_key_pair() -> tuple[str, str]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return (
        private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode(),
        private_key.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode(),
    )
