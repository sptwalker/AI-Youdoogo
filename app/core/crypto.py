"""字段级对称加密（H1.1，docs/16 P0-1）：加密存库的敏感字段（AI 卡片 api_key 等）。

设计:
- Fernet(AES-128-CBC + HMAC)对称加密;密钥由 APP_SECRET_KEY（回退 JWT_SECRET）经
  SHA-256 派生 32 字节再 urlsafe-base64，无需单独管理 Fernet 密钥格式。
- EncryptedStr:SQLAlchemy TypeDecorator，写入自动加密、读取自动解密——所有 ORM 读写点
  拿到的都是明文，业务代码零散改（service 层 c.api_key 仍是明文）。
- 兼容存量明文:解密失败（历史未加密值或密钥变更）回退原文，不炸；迁移负责把存量就地加密。
- 前缀标记:密文带 'enc:v1:' 前缀，用于区分"已加密"与"历史明文"，迁移幂等、双解码安全。

红线:密钥泄露面从"DB 明文"降为"DB 密文 + 需 APP_SECRET_KEY 才能解"。密钥本身走 .env，
不入库、不硬编码。
"""

from __future__ import annotations

import base64
import hashlib
from functools import lru_cache
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import String, TypeDecorator

from app.core.config import get_settings

_PREFIX = "enc:v1:"  # 密文标记前缀，区分已加密/历史明文


@lru_cache
def _fernet() -> Fernet:
    """由 APP_SECRET_KEY（回退 JWT_SECRET）派生 Fernet 密钥。进程级单例。"""
    s = get_settings()
    seed = (s.app_secret_key or s.jwt_secret or "").encode("utf-8")
    key = base64.urlsafe_b64encode(hashlib.sha256(seed).digest())
    return Fernet(key)


def encrypt(plain: str) -> str:
    """明文 → 带前缀密文。空串原样返回（不加密空值，便于 list 判 is_set）。"""
    if not plain:
        return plain
    token = _fernet().encrypt(plain.encode("utf-8")).decode("ascii")
    return f"{_PREFIX}{token}"


def decrypt(stored: str) -> str:
    """带前缀密文 → 明文。无前缀（历史明文）或解密失败 → 原样返回（兼容存量）。"""
    if not stored or not stored.startswith(_PREFIX):
        return stored  # 历史明文，直接用
    token = stored[len(_PREFIX):]
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        return stored  # 密钥变更/损坏：回退原文，不阻断（上层可 re-test 发现）


def is_encrypted(stored: str) -> bool:
    """该存储值是否已加密（带前缀）。迁移幂等判据。"""
    return bool(stored) and stored.startswith(_PREFIX)


class EncryptedStr(TypeDecorator):
    """透明加密字符串列:写入自动加密、读取自动解密。存量明文可读（decrypt 兼容）。

    用法:mapped_column(EncryptedStr(512))。业务代码读写此列拿到的恒为明文。
    """

    impl = String
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> Any:
        """写库前:明文 → 密文。"""
        if value is None:
            return None
        return encrypt(str(value))

    def process_result_value(self, value: Any, dialect: Any) -> Any:
        """读库后:密文 → 明文（历史明文原样）。"""
        if value is None:
            return None
        return decrypt(str(value))
