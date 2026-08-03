"""Lodge resource-server contract tests; all HTTP uses an in-process transport."""

from __future__ import annotations

import base64
import json
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core.config import Settings
from app.platform.lodge_identity.claims import LodgePrincipal
from app.platform.lodge_identity.errors import (
    LodgeIdentityConfigurationError,
    LodgeStatusDenied,
    LodgeTokenRejected,
)
from app.platform.lodge_identity.jwks import LodgeJwksClient
from app.platform.lodge_identity.service import LodgeIdentityService, service_from_settings
from app.platform.lodge_identity.status import LodgeStatusClient

ISSUER = "https://lodge.example"
JWKS_URL = "https://lodge.example/.well-known/jwks.json"
STATUS_URL = "https://lodge.example/v2/identity/status"
STATUS_SERVICE_TOKEN = "status-service-credential"
NOW = datetime(2026, 7, 30, tzinfo=UTC)
CONTRACT_FIXTURE = Path(__file__).parent / "contracts" / "lodge_identity_v2_youdoogo.json"


@pytest.fixture
async def lodge_http_clients() -> AsyncIterator[list[httpx.AsyncClient]]:
    """Own test clients centrally; production callers remain their owners."""
    clients: list[httpx.AsyncClient] = []
    yield clients
    for client in clients:
        await client.aclose()


@pytest.fixture(scope="module")
def lodge_contract() -> dict[str, Any]:
    return json.loads(CONTRACT_FIXTURE.read_text(encoding="utf-8"))


def _http_client(
    clients: list[httpx.AsyncClient], handler: Callable[[httpx.Request], Any]
) -> httpx.AsyncClient:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    clients.append(client)
    return client


def _rsa_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwk(key: rsa.RSAPrivateKey, kid: str = "key-1") -> dict[str, str]:
    numbers = key.public_key().public_numbers()

    def encode(value: int) -> str:
        return base64.urlsafe_b64encode(
            value.to_bytes((value.bit_length() + 7) // 8, "big")
        ).rstrip(b"=").decode()

    return {
        "kty": "RSA",
        "kid": kid,
        "use": "sig",
        "alg": "RS256",
        "n": encode(numbers.n),
        "e": encode(numbers.e),
    }


def _token(
    key: rsa.RSAPrivateKey,
    *,
    kid: str | None = "key-1",
    audience: str | list[str] | None = None,
    algorithm: str = "RS256",
    **overrides: Any,
) -> str:
    claims: dict[str, Any] = {
        "iss": ISSUER,
        "aud": ["youdoogo"] if audience is None else audience,
        "sub": "user:7",
        "sid": "session-9",
        "org_id": "org-3",
        "identity_ver": 4,
        "jti": "token-11",
        "iat": NOW,
        "nbf": NOW - timedelta(seconds=1),
        "exp": NOW + timedelta(minutes=5),
        "token_use": "access",
        "token_profile": "user",
        "contract_ver": "lodge_identity_v2",
        "entitlements": {
            "youdoogo": {
                "allowed": True,
                "system_role": "editor",
                "source": "explicit_grant",
                "scopes": [
                    "decision:read",
                    "decision:proposal:draft",
                    "decision:proposal:submit",
                ],
            }
        },
        "scope": [
            "decision:read",
            "decision:proposal:draft",
            "decision:proposal:submit",
        ],
    }
    claims.update(overrides)
    headers = {"typ": overrides.pop("header_typ", "at+jwt")}
    if kid is not None:
        headers["kid"] = kid
    signing_key: Any = key if algorithm == "RS256" else "not-a-lodge-secret-with-32-bytes"
    return jwt.encode(claims, signing_key, algorithm=algorithm, headers=headers)


def _status_response() -> dict[str, Any]:
    return {
        "active": True,
        "current_identity_ver": 4,
        "session_active": True,
        "subject": "user:7",
        "sid": "session-9",
        "jti": "token-11",
        "system_key": "youdoogo",
        "audience": "youdoogo",
        "org_id": "org-3",
        "entitlement": {"allowed": True},
        "scopes": ["decision:read"],
        "checked_at": "2026-07-30T00:00:00Z",
    }


def _service(
    key: rsa.RSAPrivateKey,
    *,
    clients: list[httpx.AsyncClient],
    status: dict[str, Any] | None = None,
    jwks: dict[str, Any] | None = None,
    max_response_bytes: int = 65_536,
) -> tuple[LodgeIdentityService, list[httpx.Request]]:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/.well-known/jwks.json":
            return httpx.Response(200, json=jwks or {"keys": [_jwk(key)]})
        if request.url.path == "/v2/identity/status":
            if status is not None:
                return httpx.Response(200, json=status)
            request_payload = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    **_status_response(),
                    "sid": request_payload["sid"],
                    "jti": request_payload["jti"],
                },
            )
        return httpx.Response(404)

    return (
        LodgeIdentityService(
            issuer=ISSUER,
            audience="youdoogo",
            jwks_url=JWKS_URL,
            status_url=STATUS_URL,
            status_service_token=STATUS_SERVICE_TOKEN,
            http_client=_http_client(clients, handler),
            max_response_bytes=max_response_bytes,
            now=lambda: NOW,
        ),
        requests,
    )


@pytest.mark.asyncio
async def test_lodge_user_target_token_is_verified_then_status_checked(
    lodge_http_clients: list[httpx.AsyncClient],
) -> None:
    key = _rsa_key()
    service, requests = _service(key, clients=lodge_http_clients)

    browser_token = _token(key)
    principal = await service.authenticate(browser_token)

    assert principal.subject == "user:7"
    assert principal.organization_id == "org-3"
    assert principal.identity_version == 4
    assert [request.url.path for request in requests] == [
        "/.well-known/jwks.json",
        "/v2/identity/status",
    ]
    status_request = requests[-1]
    assert status_request.method == "POST"
    assert status_request.headers["Authorization"] == f"Bearer {STATUS_SERVICE_TOKEN}"
    assert browser_token not in status_request.headers["Authorization"]
    assert browser_token not in status_request.content.decode()
    assert status_request.headers["Content-Type"] == "application/json"
    assert status_request.url.query == b""
    assert json.loads(status_request.content) == {
        "system_key": "youdoogo",
        "subject": "user:7",
        "identity_ver": 4,
        "sid": "session-9",
        "jti": "token-11",
        "audience": "youdoogo",
        "org_id": "org-3",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        ({"algorithm": "HS256"}, "algorithm"),
        ({"kid": None}, "kid"),
        ({"audience": "youdoogo"}, "audience"),
        ({"audience": ["youdoogo", "lodge"]}, "audience"),
        ({"audience": "lodge"}, "audience"),
        ({"audience": "llm_api"}, "audience"),
        ({"audience": "llm_wiki"}, "audience"),
        ({"token_use": "id"}, "token_use"),
        ({"token_profile": "delegated"}, "token_profile"),
        ({"contract_ver": "lodge_identity_v1"}, "contract_ver"),
        ({"contract_ver": None}, "contract_ver"),
        ({"iat": NOW + timedelta(minutes=1)}, "issued-at"),
        ({"exp": NOW - timedelta(seconds=1)}, "expired"),
        ({"nbf": NOW + timedelta(minutes=1)}, "not yet"),
        ({"header_typ": "JWT"}, "typ"),
        ({"sub": ""}, "malformed"),
        ({"sid": ""}, "malformed"),
        ({"org_id": ""}, "malformed"),
        ({"identity_ver": None}, "malformed"),
        ({"jti": ""}, "malformed"),
    ],
)
async def test_lodge_rejects_invalid_target_token_contract(
    kwargs: dict[str, Any], error: str, lodge_http_clients: list[httpx.AsyncClient]
) -> None:
    key = _rsa_key()
    service, _ = _service(key, clients=lodge_http_clients)

    with pytest.raises(LodgeTokenRejected, match=error):
        await service.authenticate(_token(key, **kwargs))


@pytest.mark.asyncio
async def test_unknown_kid_refreshes_jwks_once_then_rejects(
    lodge_http_clients: list[httpx.AsyncClient],
) -> None:
    key = _rsa_key()
    service, requests = _service(key, clients=lodge_http_clients)
    token = _token(key, kid="rotated-key")

    with pytest.raises(LodgeTokenRejected, match="unknown kid"):
        await service.authenticate(token)
    with pytest.raises(LodgeTokenRejected, match="unknown kid"):
        await service.authenticate(token)

    assert [request.url.path for request in requests].count("/.well-known/jwks.json") == 2


@pytest.mark.asyncio
async def test_status_mismatch_revocation_or_network_failure_is_denied(
    lodge_http_clients: list[httpx.AsyncClient],
) -> None:
    key = _rsa_key()
    statuses = [
        {**_status_response(), "subject": "user:8"},
        {**_status_response(), "org_id": "other-org"},
        {**_status_response(), "system_key": "other-system"},
        {**_status_response(), "current_identity_ver": 3},
        {**_status_response(), "session_active": False},
        {**_status_response(), "entitlement": {"allowed": False}},
        {"malformed": True},
    ]
    statuses.extend(
        {name: value for name, value in _status_response().items() if name != field}
        for field in (
            "active",
            "current_identity_ver",
            "session_active",
            "org_id",
            "entitlement",
            "subject",
            "system_key",
        )
    )
    for status in statuses:
        service, _ = _service(key, clients=lodge_http_clients, status=status)
        with pytest.raises(LodgeStatusDenied):
            await service.authenticate(_token(key))

    def status_timeout(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/.well-known/jwks.json":
            return httpx.Response(200, json={"keys": [_jwk(key)]})
        raise httpx.ReadTimeout("timeout")

    timeout_service = LodgeIdentityService(
        issuer=ISSUER,
        audience="youdoogo",
        jwks_url=JWKS_URL,
        status_url=STATUS_URL,
        status_service_token=STATUS_SERVICE_TOKEN,
        http_client=_http_client(lodge_http_clients, status_timeout),
        now=lambda: NOW,
    )
    browser_token = _token(key)
    with pytest.raises(LodgeStatusDenied) as failure:
        await timeout_service.authenticate(browser_token)
    assert STATUS_SERVICE_TOKEN not in str(failure.value)
    assert browser_token not in str(failure.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    [
        {**_status_response(), "sid": "another-session"},
        {**_status_response(), "jti": "another-token"},
        {**_status_response(), "audience": "another-audience"},
        {key: value for key, value in _status_response().items() if key != "sid"},
        {key: value for key, value in _status_response().items() if key != "jti"},
        {key: value for key, value in _status_response().items() if key != "audience"},
    ],
    ids=(
        "wrong-sid",
        "wrong-jti",
        "wrong-audience",
        "missing-sid",
        "missing-jti",
        "missing-audience",
    ),
)
async def test_status_response_must_bind_the_exact_verified_identity_context(
    status: dict[str, Any],
    lodge_http_clients: list[httpx.AsyncClient],
) -> None:
    key = _rsa_key()
    service, _ = _service(key, clients=lodge_http_clients, status=status)

    with pytest.raises(LodgeStatusDenied):
        await service.authenticate(_token(key))


@pytest.mark.asyncio
async def test_status_response_limit_and_cache_are_fail_closed_per_token_jti(
    lodge_http_clients: list[httpx.AsyncClient],
) -> None:
    key = _rsa_key()
    oversized_service, _ = _service(
        key,
        clients=lodge_http_clients,
        status={"padding": "x" * 2_048},
        max_response_bytes=1_024,
    )
    with pytest.raises(LodgeStatusDenied):
        await oversized_service.authenticate(_token(key))

    service, requests = _service(key, clients=lodge_http_clients)
    await service.authenticate(_token(key, jti="token-one"))
    await service.authenticate(_token(key, jti="token-two"))
    assert [request.url.path for request in requests].count("/v2/identity/status") == 2


@pytest.mark.asyncio
async def test_jwks_network_and_response_limit_fail_closed(
    lodge_http_clients: list[httpx.AsyncClient],
) -> None:
    key = _rsa_key()

    async def unavailable(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout")

    unavailable_service = LodgeIdentityService(
        issuer=ISSUER,
        audience="youdoogo",
        jwks_url=JWKS_URL,
        status_url=STATUS_URL,
        status_service_token=STATUS_SERVICE_TOKEN,
        http_client=_http_client(lodge_http_clients, unavailable),
        now=lambda: NOW,
    )
    with pytest.raises(LodgeTokenRejected, match="JWKS is unavailable"):
        await unavailable_service.authenticate(_token(key))

    oversized = LodgeJwksClient(
        url=JWKS_URL,
        http_client=_http_client(
            lodge_http_clients, lambda _: httpx.Response(200, content=b"x" * 32)
        ),
        max_response_bytes=8,
    )
    with pytest.raises(LodgeTokenRejected, match="JWKS is unavailable"):
        await oversized.key_for("key-1")


def test_enabled_lodge_feature_requires_all_remote_configuration() -> None:
    with pytest.raises(ValueError, match="LODGE"):
        Settings(lodge_identity_enabled=True, _env_file=None)

    settings = Settings(
        lodge_identity_enabled=True,
        lodge_issuer=ISSUER,
        lodge_jwks_url=JWKS_URL,
        lodge_status_url=STATUS_URL,
        lodge_status_service_token=STATUS_SERVICE_TOKEN,
        _env_file=None,
    )
    with pytest.raises(LodgeIdentityConfigurationError, match="HTTP client"):
        service_from_settings(settings)

    with pytest.raises(ValueError, match="LODGE_STATUS_SERVICE_TOKEN"):
        Settings(
            lodge_identity_enabled=True,
            lodge_issuer=ISSUER,
            lodge_jwks_url=JWKS_URL,
            lodge_status_url=STATUS_URL,
            _env_file=None,
        )


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("lodge_issuer", "http://lodge.example"),
        ("lodge_issuer", "https://user@lodge.example"),
        ("lodge_issuer", "https://lodge.example#fragment"),
        ("lodge_jwks_url", "https://lodge.example/"),
        ("lodge_jwks_url", "https://user@lodge.example/jwks.json"),
        ("lodge_jwks_url", "https://lodge.example/jwks.json#fragment"),
        ("lodge_status_url", "http://lodge.example/v2/identity/status"),
        ("lodge_status_url", "https://user@lodge.example/v2/identity/status"),
        ("lodge_status_url", "https://lodge.example/v2/identity/status#fragment"),
        ("lodge_audience", "youdoogo "),
        ("lodge_http_timeout_seconds", 0),
        ("lodge_jwks_cache_ttl_seconds", 3_601),
        ("lodge_status_cache_ttl_seconds", 301),
        ("lodge_response_max_bytes", 1_048_577),
        ("lodge_status_cache_max_entries", 0),
        ("lodge_status_service_token", "  "),
    ],
)
def test_enabled_lodge_settings_fail_fast_for_unsafe_remote_configuration(
    field: str, invalid_value: object
) -> None:
    values: dict[str, object] = {
        "lodge_identity_enabled": True,
        "lodge_issuer": ISSUER,
        "lodge_jwks_url": JWKS_URL,
        "lodge_status_url": STATUS_URL,
        "lodge_status_service_token": STATUS_SERVICE_TOKEN,
        "_env_file": None,
    }
    values[field] = invalid_value

    with pytest.raises(ValueError):
        Settings(**values)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_status_cache_collects_expired_entries_and_evicts_oldest_expiry(
    lodge_http_clients: list[httpx.AsyncClient],
) -> None:
    now = 0.0
    requests: list[httpx.Request] = []

    def clock() -> float:
        return now

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        payload = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                **_status_response(),
                "subject": payload["subject"],
                "sid": payload["sid"],
                "jti": payload["jti"],
                "identity_ver": payload["identity_ver"],
                "org_id": payload["org_id"],
            },
        )

    status = LodgeStatusClient(
        url=STATUS_URL,
        service_token=STATUS_SERVICE_TOKEN,
        http_client=_http_client(lodge_http_clients, handler),
        cache_ttl_seconds=10,
        cache_max_entries=2,
        clock=clock,
    )

    def principal(token_id: str) -> LodgePrincipal:
        return LodgePrincipal(
            subject="user:7",
            session_id="session-9",
            organization_id="org-3",
            identity_version=4,
            token_id=token_id,
            issued_at=NOW,
            expires_at=NOW + timedelta(minutes=5),
        )

    first = principal("token-one")
    second = principal("token-two")
    third = principal("token-three")
    await status.require_active(first)
    now = 11.0
    await status.require_active(second)  # Clears first, whose entry expired at 10.
    now = 12.0
    await status.require_active(first)  # An expired entry must not skip the status request.
    now = 13.0
    # Capacity eviction removes second (expiry 21 before first's 22).
    await status.require_active(third)

    assert len(status._cache) == 2
    await status.require_active(second)
    assert [json.loads(request.content)["jti"] for request in requests] == [
        "token-one",
        "token-two",
        "token-one",
        "token-three",
        "token-two",
    ]


@pytest.mark.asyncio
async def test_consumer_uses_versioned_lodge_contract_fixture(
    lodge_contract: dict[str, Any], lodge_http_clients: list[httpx.AsyncClient]
) -> None:
    assert lodge_contract["schema_version"] == "1.0"
    contract = lodge_contract["contract"]
    assert contract["version"] == "lodge_identity_v2"
    assert contract["system_key"] == "youdoogo"
    assert contract["source"] == {
        "repository": "nexus/lodge",
        "source_base_commit": "51b73fa",
        "commit_policy": (
            "The fixture is versioned by schema_version and source_base_commit so it does not "
            "need to name its own publishing commit."
        ),
    }

    jwt_contract = lodge_contract["jwt"]
    claim_contract = jwt_contract["claims"]
    audience = claim_contract["audience"]["exactly"]
    entitlement = {
        "allowed": True,
        "system_role": "editor",
        "source": "explicit_grant",
        "scopes": lodge_contract["scope_ceilings"]["editor"],
    }
    claims: dict[str, Any] = {
        "contract_ver": claim_contract["contract_ver"],
        "token_use": claim_contract["token_use"],
        "token_profile": claim_contract["token_profile"],
        "iss": ISSUER,
        "aud": audience,
        "sub": "user:7",
        "sid": "session-9",
        "org_id": "org-3",
        "identity_ver": 4,
        "jti": "token-11",
        "iat": NOW,
        "nbf": NOW - timedelta(seconds=1),
        "exp": NOW + timedelta(seconds=claim_contract["ttl_seconds_max"]),
        "entitlements": {contract["system_key"]: entitlement},
        "scope": entitlement["scopes"],
    }
    assert set(claim_contract["required"]) == set(claims)
    assert claim_contract["entitlement"]["required_fields"] == list(entitlement)
    assert set(claims[claim_contract["scope"]["claim"]]) <= set(
        lodge_contract[claim_contract["scope"]["must_not_exceed"]][entitlement["system_role"]]
    )
    assert set(claims["scope"]).isdisjoint(lodge_contract["forbidden_scopes"])

    cookie = lodge_contract["cookie"]
    assert cookie == {
        "name": "lodge_youdoogo_token",
        "path": "/youdoogo",
        "host_only": True,
        "secure": True,
        "http_only": True,
        "same_site": "Lax",
    }

    key = _rsa_key()
    header = jwt_contract["header"]
    token = jwt.encode(
        claims,
        key,
        algorithm=header["alg"],
        headers={"typ": header["typ"], "kid": "key-1"},
    )
    token_header = jwt.get_unverified_header(token)
    assert token_header["alg"] == header["alg"]
    assert token_header["typ"] == header["typ"]
    assert header["kid"]["required"] is True
    assert token_header["kid"]

    request_contract = lodge_contract["status"]["request"]
    status_request = {
        "system_key": contract["system_key"],
        "subject": claims["sub"],
        "identity_ver": claims["identity_ver"],
        "sid": claims["sid"],
        "jti": claims["jti"],
        "audience": audience[0],
        "org_id": claims["org_id"],
    }
    active_response = {
        "active": True,
        "current_identity_ver": claims["identity_ver"],
        "session_active": True,
        "entitlement": entitlement,
        "checked_at": "2026-07-30T00:00:00Z",
        "subject": claims["sub"],
        "system_key": contract["system_key"],
        "audience": audience[0],
        "org_id": claims["org_id"],
        "sid": claims["sid"],
        "jti": claims["jti"],
        "scopes": claims["scope"],
    }
    assert set(active_response) == set(
        lodge_contract["status"]["response"]["active"]["required_fields"]
    )
    denied_response = {
        "active": False,
        "current_identity_ver": claims["identity_ver"],
        "session_active": False,
        "entitlement": {"allowed": False},
        "checked_at": "2026-07-30T00:00:00Z",
    }
    denied_contract = lodge_contract["status"]["response"]["denied"]
    assert set(denied_response) == set(denied_contract["required_fields"])
    assert set(denied_response).isdisjoint(denied_contract["absent_fields"])

    status_contract = lodge_contract["status"]

    def service_for(status: dict[str, Any]) -> tuple[LodgeIdentityService, list[httpx.Request]]:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.url.path == "/.well-known/jwks.json":
                return httpx.Response(200, json={"keys": [_jwk(key)]})
            if request.url.path == status_contract["path"]:
                return httpx.Response(200, json=status)
            return httpx.Response(404)

        return (
            LodgeIdentityService(
                issuer=ISSUER,
                audience=contract["system_key"],
                jwks_url=JWKS_URL,
                status_url=f"https://lodge.example{status_contract['path']}",
                status_service_token=STATUS_SERVICE_TOKEN,
                http_client=_http_client(lodge_http_clients, handler),
                now=lambda: NOW,
            ),
            requests,
        )

    service, requests = service_for(active_response)
    await service.authenticate(token)
    sent_request = requests[-1]
    assert sent_request.method == status_contract["method"]
    assert sent_request.url.path == status_contract["path"]
    assert sent_request.headers["Authorization"] == f"Bearer {STATUS_SERVICE_TOKEN}"
    assert token not in sent_request.headers["Authorization"]
    assert json.loads(sent_request.content) == status_request
    assert set(status_request) == set(request_contract["required_fields"])
    assert status_request["system_key"] == request_contract["constraints"]["system_key"]
    assert status_request["audience"] == request_contract["constraints"]["audience"]
    assert status_request["audience"] == status_request["system_key"]
    assert status_request["identity_ver"] > 0

    for required_claim in claim_contract["required"]:
        missing_claims = dict(claims)
        missing_claims.pop(required_claim)
        missing_token = jwt.encode(
            missing_claims,
            key,
            algorithm=header["alg"],
            headers={"typ": header["typ"], "kid": "key-1"},
        )
        missing_service, _ = service_for(active_response)
        with pytest.raises(LodgeTokenRejected):
            await missing_service.authenticate(missing_token)

    for invalid_claims in (
        {**claims, "aud": [*audience, "lodge"]},
        {
            **claims,
            "exp": NOW + timedelta(seconds=claim_contract["ttl_seconds_max"] + 1),
        },
        {
            **claims,
            "scope": [*claims["scope"], lodge_contract["forbidden_scopes"][0]],
        },
    ):
        invalid_token = jwt.encode(
            invalid_claims,
            key,
            algorithm=header["alg"],
            headers={"typ": header["typ"], "kid": "key-1"},
        )
        invalid_service, _ = service_for(active_response)
        with pytest.raises(LodgeTokenRejected):
            await invalid_service.authenticate(invalid_token)

    mismatched_service, _ = service_for({**active_response, "jti": "other-token"})
    with pytest.raises(LodgeStatusDenied):
        await mismatched_service.authenticate(token)

    denied_service, _ = service_for(denied_response)
    with pytest.raises(LodgeStatusDenied):
        await denied_service.authenticate(token)


def test_lodge_adr_is_numbered_and_indexed() -> None:
    adr_dir = CONTRACT_FIXTURE.parent.parent.parent / "docs" / "adr"
    assert (adr_dir / "0010-lodge-resource-server-foundation.md").is_file()
    assert not (adr_dir / "ADR-019-lodge-resource-server-foundation.md").exists()
    assert "[0010](0010-lodge-resource-server-foundation.md)" in (adr_dir / "README.md").read_text(
        encoding="utf-8"
    )
