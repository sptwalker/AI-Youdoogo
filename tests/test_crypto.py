"""字段级加密单测（H1.1，docs/16 P0-1）:加解密往返 + 存量明文兼容 + ORM 透明加密。"""

import uuid
from collections.abc import AsyncGenerator

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core import crypto
from app.models import Base
from app.models.ai_provider import AiProvider


# ── 纯函数:加解密 ───────────────────────────────────────
def test_encrypt_decrypt_roundtrip() -> None:
    plain = "sk-secret-abcdef123456"
    enc = crypto.encrypt(plain)
    assert enc != plain and enc.startswith("enc:v1:")
    assert crypto.decrypt(enc) == plain


def test_encrypt_empty_passthrough() -> None:
    """空串不加密（便于 is_set 判断）。"""
    assert crypto.encrypt("") == ""
    assert crypto.decrypt("") == ""


def test_decrypt_legacy_plaintext() -> None:
    """历史明文（无前缀）→ 原样返回，兼容存量。"""
    assert crypto.decrypt("sk-old-plaintext-key") == "sk-old-plaintext-key"


def test_is_encrypted() -> None:
    assert crypto.is_encrypted(crypto.encrypt("x")) is True
    assert crypto.is_encrypted("plain") is False
    assert crypto.is_encrypted("") is False


def test_ciphertext_differs_each_call() -> None:
    """Fernet 含随机 IV：同明文两次密文不同，但都能解回。"""
    a, b = crypto.encrypt("same"), crypto.encrypt("same")
    assert a != b
    assert crypto.decrypt(a) == crypto.decrypt(b) == "same"


# ── ORM 透明加密：写库密文、读回明文 ────────────────────
@pytest.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


async def test_orm_stores_ciphertext_returns_plaintext(db: AsyncSession) -> None:
    """ORM 写入自动加密（库里是密文）、读取自动解密（拿到明文）。"""
    card = AiProvider(
        id=uuid.uuid4(), name="卡", tier="daily", base_url="https://x.com",
        api_key="sk-plain-secret-999", model="m1",
    )
    db.add(card)
    await db.commit()

    # 底层原始值应为密文（绕过 TypeDecorator 直接读列）
    raw = (await db.execute(
        text("SELECT api_key FROM ai_provider WHERE name='卡'")
    )).scalar_one()
    assert raw.startswith("enc:v1:") and "sk-plain-secret-999" not in raw

    # ORM 读回自动解密为明文
    got = (await db.execute(select(AiProvider).where(AiProvider.name == "卡"))).scalar_one()
    assert got.api_key == "sk-plain-secret-999"
