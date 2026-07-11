"""密码哈希与 JWT 令牌（鉴权核心原语）。

登出策略：无状态 JWT，登出=客户端丢弃令牌。
ponytail: 无服务端吊销，需要强制下线时再加 Redis 黑名单。
"""

import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from app.core.config import get_settings
from app.core.exceptions import AppError

ALGORITHM = "HS256"

# 用户不存在时也跑一次校验，使登录两分支耗时一致（防用户名时序枚举）
DUMMY_HASH = bcrypt.hashpw(b"timing-equalizer", bcrypt.gensalt()).decode()


def hash_password(password: str) -> str:
    """bcrypt 哈希（自带盐）。

    Raises:
        AppError: 密码 UTF-8 编码超过 bcrypt 的 72 字节上限（统一 400，而非 500）。
    """
    if len(password.encode()) > 72:
        raise AppError("密码过长：UTF-8 编码后不得超过 72 字节", code=400, status_code=400)
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    """校验明文密码与哈希是否匹配。"""
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:  # 哈希格式非法（脏数据）按不匹配处理
        return False


def create_access_token(user_id: uuid.UUID, role_code: str) -> str:
    """签发访问令牌：sub=用户ID，role=角色码。"""
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "role": role_code,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    """解码并校验令牌（含过期校验）。

    Raises:
        jwt.InvalidTokenError: 令牌非法或已过期（含子类 ExpiredSignatureError）。
    """
    return jwt.decode(token, get_settings().jwt_secret, algorithms=[ALGORITHM])
