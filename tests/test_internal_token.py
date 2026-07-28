"""Internal JWT 底座单测（C1）：ES256 自签自验 + 拒绝路径 + require_service scope 判定。

密钥在测试内现生成一对 EC（不落盘、不依赖 .env），monkeypatch 进 settings 单例。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from app.contexts.shared_kernel import (
    AuthenticationFailed,
    InvalidInput,
    PermissionDenied,
)
from app.core.config import get_settings
from app.core.internal_token import (
    ALGORITHM,
    mint_internal_token,
    verify_internal_token,
)

_AUD = "youdoogo-platform"


def _ec_pem_pair() -> tuple[str, str]:
    key = ec.generate_private_key(ec.SECP256R1())
    priv = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    pub = (
        key.public_key()
        .public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        .decode()
    )
    return priv, pub


@pytest.fixture
def keyed_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """给进程 settings 单例注入一对 EC 密钥 + issuer/exp（公钥留空走派生）。"""
    priv, _pub = _ec_pem_pair()
    settings = get_settings()
    monkeypatch.setattr(settings, "internal_jwt_private_key", priv)
    monkeypatch.setattr(settings, "internal_jwt_public_key", "")
    monkeypatch.setattr(settings, "internal_jwt_issuer", _AUD)
    monkeypatch.setattr(settings, "internal_jwt_expire_seconds", 300)


def test_mint_then_verify_roundtrip(keyed_settings: None) -> None:
    token = mint_internal_token(
        service_id="llm-adapter",
        audience=_AUD,
        scope=("llm:invoke", "llm:embed"),
        actor_id="user-123",
    )
    claims = verify_internal_token(token, audience=_AUD)
    assert claims.service_id == "llm-adapter"
    assert claims.actor_id == "user-123"
    assert claims.scope == ("llm:invoke", "llm:embed")
    assert claims.issuer == _AUD
    assert claims.audience == _AUD


def test_verify_rejects_wrong_audience(keyed_settings: None) -> None:
    token = mint_internal_token(service_id="s", audience="other-service")
    with pytest.raises(AuthenticationFailed):
        verify_internal_token(token, audience=_AUD)


def test_verify_rejects_wrong_issuer(keyed_settings: None, monkeypatch: pytest.MonkeyPatch) -> None:
    token = mint_internal_token(service_id="s", audience=_AUD)
    # 验签方期望的 iss 变了 → 拒
    monkeypatch.setattr(get_settings(), "internal_jwt_issuer", "someone-else")
    with pytest.raises(AuthenticationFailed):
        verify_internal_token(token, audience=_AUD)


def test_verify_rejects_expired(keyed_settings: None) -> None:
    settings = get_settings()
    now = datetime.now(UTC)
    expired = jwt.encode(
        {
            "iss": _AUD,
            "aud": _AUD,
            "sub": "s",
            "service_id": "s",
            "actor": None,
            "scope": [],
            "iat": now - timedelta(seconds=600),
            "exp": now - timedelta(seconds=300),
        },
        settings.internal_jwt_private_key,
        algorithm=ALGORITHM,
    )
    with pytest.raises(AuthenticationFailed):
        verify_internal_token(expired, audience=_AUD)


def test_verify_rejects_hs256_confusion(keyed_settings: None) -> None:
    # 拿对称密钥签个 HS256 token → 必须被 algorithms=["ES256"] 拒（信任边界关键用例）
    forged = jwt.encode(
        {
            "iss": _AUD,
            "aud": _AUD,
            "sub": "attacker",
            "service_id": "attacker",
            "scope": ["llm:invoke"],
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(seconds=300),
        },
        "any-symmetric-secret",
        algorithm="HS256",
    )
    with pytest.raises(AuthenticationFailed):
        verify_internal_token(forged, audience=_AUD)


def test_mint_without_private_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "internal_jwt_private_key", "")
    with pytest.raises(InvalidInput):
        mint_internal_token(service_id="s", audience=_AUD)


async def test_require_service_scope_subset_passes(keyed_settings: None) -> None:
    from app.api.deps import require_service

    token = mint_internal_token(
        service_id="s", audience=_AUD, scope=("llm:invoke", "llm:embed")
    )
    guard = require_service("llm:invoke")
    claims = await guard(_bearer_creds(token))
    assert claims.service_id == "s"


async def test_require_service_missing_scope_denied(keyed_settings: None) -> None:
    from app.api.deps import require_service

    token = mint_internal_token(service_id="s", audience=_AUD, scope=("llm:embed",))
    guard = require_service("llm:invoke")
    with pytest.raises(PermissionDenied):
        await guard(_bearer_creds(token))


def _bearer_creds(token: str):  # type: ignore[no-untyped-def]
    from fastapi.security import HTTPAuthorizationCredentials

    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
