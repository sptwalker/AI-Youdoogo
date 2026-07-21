"""飞书 SSO 登录单测（I2，docs/18）:login_by_feishu 开户/复用/停用（打桩飞书 client）。"""

import uuid
from collections.abc import AsyncGenerator
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.exceptions import AppError
from app.models import Base
from app.models.system import SysUser
from app.services import auth_service


@pytest.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


def _stub_oauth(monkeypatch: pytest.MonkeyPatch, info: dict[str, Any]) -> None:
    from app.integrations.feishu import client as fc

    async def _info(code: str) -> dict[str, Any]:
        return info

    monkeypatch.setattr(fc.feishu_client, "oauth_user_info", _info)


async def test_feishu_login_creates_user(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """首次飞书登录 → 自动开户（member 最低权限）。"""
    _stub_oauth(monkeypatch, {"open_id": "ou_new", "name": "王五", "en_name": "Wu Wang"})
    user = await auth_service.login_by_feishu(db, "code123")
    assert user.feishu_open_id == "ou_new" and user.real_name == "王五"
    assert user.role_code == "member" and user.en_name == "Wu Wang"


async def test_feishu_login_reuses_existing(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """已存在（如 I1 同步预建）→ 复用不新建。"""
    existing = SysUser(
        id=uuid.uuid4(), username="fs_ou_x", password_hash="!feishu-sso",
        feishu_open_id="ou_x", role_code="member", real_name="张三",
    )
    db.add(existing)
    await db.commit()
    _stub_oauth(monkeypatch, {"open_id": "ou_x", "name": "张三"})
    user = await auth_service.login_by_feishu(db, "code")
    assert user.id == existing.id
    n = (await db.execute(select(func.count()).select_from(SysUser))).scalar_one()
    assert n == 1  # 未新建


async def test_feishu_login_no_open_id_fails(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_oauth(monkeypatch, {"name": "无标识"})
    with pytest.raises(AppError, match="标识"):
        await auth_service.login_by_feishu(db, "code")


async def test_feishu_login_disabled_blocked(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """停用账号 → 拒绝登录。"""
    db.add(SysUser(
        id=uuid.uuid4(), username="fs_ou_off", password_hash="x",
        feishu_open_id="ou_off", role_code="member", is_active=False,
    ))
    await db.commit()
    _stub_oauth(monkeypatch, {"open_id": "ou_off", "name": "停用"})
    with pytest.raises(AppError, match="停用"):
        await auth_service.login_by_feishu(db, "code")


def test_oauth_authorize_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """授权 URL 含 app_id + redirect_uri。"""
    from app.integrations.feishu import client as fc

    monkeypatch.setattr(fc.FeishuClient, "_creds", staticmethod(lambda: ("cli_app123", "sec")))
    url = fc.feishu_client.oauth_authorize_url("https://app/cb", state="s1")
    assert "cli_app123" in url and "redirect_uri=https" in url and "state=s1" in url
