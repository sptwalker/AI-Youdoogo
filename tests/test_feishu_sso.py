"""飞书 SSO 登录单测（I2，docs/18）：预绑定解析/角色保留/停用（打桩飞书 client）。"""

import uuid
from collections.abc import AsyncGenerator
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.contexts.foundations.identity.entrypoints import operations as auth_service
from app.contexts.shared_kernel import ApplicationError
from app.models import Base
from app.models.system import SysUser


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


async def test_feishu_login_rejects_unbound_user_without_creating_account(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """未预绑定身份拒绝登录，且不会因姓名等资料自动开户。"""
    _stub_oauth(monkeypatch, {"open_id": "ou_new_123456", "name": "王五", "en_name": "Wu Wang"})
    with pytest.raises(ApplicationError, match="暂无系统访问权限"):
        await auth_service.login_by_feishu(db, code="code123")
    assert (await db.execute(select(func.count()).select_from(SysUser))).scalar_one() == 0


async def test_feishu_login_reuses_existing(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """已预绑定管理员 → 复用同一账号并保留数据库角色。"""
    existing = SysUser(
        id=uuid.uuid4(),
        username="fs_ou_x",
        password_hash="!feishu-sso",
        feishu_open_id="ou_existing_123456",
        role_code="admin",
        real_name="张三",
    )
    db.add(existing)
    await db.commit()
    _stub_oauth(monkeypatch, {"open_id": "ou_existing_123456", "name": "张三"})
    user = await auth_service.login_by_feishu(db, code="code")
    assert user.id == existing.id
    assert user.role_code == "admin"
    n = (await db.execute(select(func.count()).select_from(SysUser))).scalar_one()
    assert n == 1  # 未新建


async def test_feishu_login_no_open_id_fails(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_oauth(monkeypatch, {"name": "无标识"})
    with pytest.raises(ApplicationError, match="标识"):
        await auth_service.login_by_feishu(db, code="code")


async def test_feishu_login_disabled_blocked(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """停用账号 → 拒绝登录。"""
    db.add(
        SysUser(
            id=uuid.uuid4(),
            username="fs_ou_off",
            password_hash="x",
            feishu_open_id="ou_offline_123456",
            role_code="member",
            is_active=False,
        )
    )
    await db.commit()
    _stub_oauth(monkeypatch, {"open_id": "ou_offline_123456", "name": "停用"})
    with pytest.raises(ApplicationError, match="暂无系统访问权限"):
        await auth_service.login_by_feishu(db, code="code")


def test_oauth_authorize_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """授权 URL 含 app_id + redirect_uri。"""
    from app.integrations.feishu import client as fc

    monkeypatch.setattr(fc.FeishuClient, "_creds", staticmethod(lambda: ("cli_app123", "sec")))
    url = fc.feishu_client.oauth_authorize_url("https://app/cb", state="s1")
    assert "cli_app123" in url and "redirect_uri=https" in url and "state=s1" in url
