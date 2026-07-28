"""Internal JWT：服务间鉴权令牌（C1 / docs/21 §9）。

与面向用户的对称 HS256 令牌（``app/core/security.py``）**彻底隔离**：非对称 ES256、独立密钥、
claims 承载服务身份而非用户身份。文档红线（§9 L1414 / §12 风险表）：不共享业务 ``jwt_secret``、
远端服务只持验证公钥。

claims（docs/21 §9 L1413）：``iss``/``aud``/``service_id``/``actor``/``scope``/``exp≤5min``。
``sub`` = service_id（服务即主体）；``actor`` 承载「代表哪个真人」（= §8 Envelope actor_id，可空）。

ponytail: 无 jti / Redis 黑名单——exp≤5min 已大幅压缩重放窗口，本轮不做防重放；
需强制吊销/防重放时加 Redis jti 缓存（升级路径）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
    load_pem_private_key,
)

from app.contexts.shared_kernel import AuthenticationFailed, InvalidInput
from app.core.config import get_settings

ALGORITHM = "ES256"  # 非对称椭圆曲线 P-256；锁定于此以防 alg 混淆攻击（HS/none）


@dataclass(frozen=True, slots=True)
class InternalClaims:
    """校验通过的服务身份声明。"""

    service_id: str
    actor_id: str | None
    scope: tuple[str, ...]
    issuer: str
    audience: str


def _public_key_pem() -> str:
    """验签公钥 PEM：显式配置优先；留空则从私钥派生（单进程自签自验）。"""
    settings = get_settings()
    if settings.internal_jwt_public_key:
        return settings.internal_jwt_public_key
    if not settings.internal_jwt_private_key:
        raise AuthenticationFailed("Internal JWT 未配置密钥，无法验签")
    private = load_pem_private_key(settings.internal_jwt_private_key.encode(), password=None)
    pub = private.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
    return pub.decode()


def mint_internal_token(
    *,
    service_id: str,
    audience: str,
    scope: tuple[str, ...] = (),
    actor_id: str | None = None,
) -> str:
    """签发服务身份令牌（ES256，exp≤5min）。私钥未配 → 抛错，不静默签发无效令牌。"""
    settings = get_settings()
    if not settings.internal_jwt_private_key:
        raise InvalidInput("Internal JWT 私钥未配置（INTERNAL_JWT_PRIVATE_KEY），无法签发")
    now = datetime.now(UTC)
    payload = {
        "iss": settings.internal_jwt_issuer,
        "aud": audience,
        "sub": service_id,
        "service_id": service_id,
        "actor": actor_id,
        "scope": list(scope),
        "iat": now,
        "exp": now + timedelta(seconds=settings.internal_jwt_expire_seconds),
    }
    return jwt.encode(payload, settings.internal_jwt_private_key, algorithm=ALGORITHM)


def verify_internal_token(token: str, *, audience: str) -> InternalClaims:
    """验签并校验服务令牌。锁定 ES256 + 强制 aud/iss/exp/sub（信任边界，缺一不可）。

    Raises:
        AuthenticationFailed: 签名非法/过期/算法混淆/aud/iss 不符/缺必需 claim。
    """
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            _public_key_pem(),
            algorithms=[ALGORITHM],  # 锁定 ES256：拒 alg=none 与 HS256 混淆攻击
            audience=audience,
            issuer=settings.internal_jwt_issuer,
            options={"require": ["exp", "iss", "aud", "sub"]},
        )
    except jwt.InvalidTokenError as exc:
        raise AuthenticationFailed("Internal JWT 无效或已过期") from exc
    scope_raw = payload.get("scope") or []
    return InternalClaims(
        service_id=str(payload["service_id"]),
        actor_id=payload.get("actor"),
        scope=tuple(str(s) for s in scope_raw),
        issuer=str(payload["iss"]),
        audience=str(payload["aud"]),
    )
