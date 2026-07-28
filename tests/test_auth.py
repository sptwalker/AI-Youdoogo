"""JWT 鉴权体系端到端测试（内存 SQLite，不依赖 PostgreSQL/Docker）。"""

from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.security import hash_password
from app.main import app
from app.models import Base
from app.models.system import SysUser
from app.platform.database import get_db


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """内存库 + 预置 admin/member 两个用户的测试客户端。"""
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        session.add_all(
            [
                SysUser(
                    username="boss", password_hash=hash_password("admin-pass-8"),
                    role_code="admin",
                ),
                SysUser(
                    username="staff", password_hash=hash_password("member-pass-8"),
                    role_code="member",
                ),
                SysUser(
                    username="gone", password_hash=hash_password("gone-pass-88"),
                    role_code="member", is_active=False,
                ),
            ]
        )
        await session.commit()

    async def _override_db() -> AsyncGenerator:
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
    await engine.dispose()


async def _login(client: AsyncClient, username: str, password: str) -> str:
    resp = await client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_login_ok_and_me(client: AsyncClient) -> None:
    token = await _login(client, "boss", "admin-pass-8")
    resp = await client.get("/api/v1/auth/me", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["data"]["username"] == "boss"
    assert resp.json()["data"]["role_code"] == "admin"


async def test_login_wrong_password(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/auth/login", json={"username": "boss", "password": "wrong"})
    assert resp.status_code == 401


async def test_login_inactive_user(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/auth/login", json={"username": "gone", "password": "gone-pass-88"}
    )
    assert resp.status_code == 403


async def test_me_without_token(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401


async def test_me_with_garbage_token(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/auth/me", headers=_auth("not-a-jwt"))
    assert resp.status_code == 401


async def test_role_guard_member_denied(client: AsyncClient) -> None:
    token = await _login(client, "staff", "member-pass-8")
    resp = await client.get("/api/v1/users", headers=_auth(token))
    assert resp.status_code == 403


async def test_admin_user_crud_flow(client: AsyncClient) -> None:
    token = await _login(client, "boss", "admin-pass-8")

    # 创建
    resp = await client.post(
        "/api/v1/users",
        headers=_auth(token),
        json={"username": "ops01", "password": "ops-pass-88", "role_code": "member"},
    )
    assert resp.status_code == 200, resp.text
    user_id = resp.json()["data"]["id"]

    # 重名拒绝
    resp = await client.post(
        "/api/v1/users",
        headers=_auth(token),
        json={"username": "ops01", "password": "ops-pass-88"},
    )
    assert resp.status_code == 409

    # 非法角色拒绝
    resp = await client.post(
        "/api/v1/users",
        headers=_auth(token),
        json={"username": "ops02", "password": "ops-pass-88", "role_code": "superroot"},
    )
    assert resp.status_code == 400

    # 列表
    resp = await client.get("/api/v1/users", headers=_auth(token))
    assert resp.status_code == 200
    assert any(u["username"] == "ops01" for u in resp.json()["data"])

    # 停用后登录即失效
    resp = await client.patch(
        f"/api/v1/users/{user_id}", headers=_auth(token), json={"is_active": False}
    )
    assert resp.status_code == 200
    resp = await client.post(
        "/api/v1/auth/login", json={"username": "ops01", "password": "ops-pass-88"}
    )
    assert resp.status_code == 403


async def test_disabled_user_token_immediately_invalid(client: AsyncClient) -> None:
    """已签发令牌的用户被停用后，令牌立即失效（实时查库）。"""
    admin_token = await _login(client, "boss", "admin-pass-8")
    staff_token = await _login(client, "staff", "member-pass-8")

    resp = await client.get("/api/v1/users", headers=_auth(admin_token))
    staff_id = next(u["id"] for u in resp.json()["data"] if u["username"] == "staff")
    await client.patch(
        f"/api/v1/users/{staff_id}", headers=_auth(admin_token), json={"is_active": False}
    )

    resp = await client.get("/api/v1/auth/me", headers=_auth(staff_token))
    assert resp.status_code == 403


async def test_refresh(client: AsyncClient) -> None:
    token = await _login(client, "boss", "admin-pass-8")
    resp = await client.post("/api/v1/auth/refresh", headers=_auth(token))
    assert resp.status_code == 200
    new_token = resp.json()["data"]["access_token"]
    resp = await client.get("/api/v1/auth/me", headers=_auth(new_token))
    assert resp.status_code == 200


async def test_admin_cannot_lock_self(client: AsyncClient) -> None:
    """admin 不能停用或降权自己（防自锁）。"""
    token = await _login(client, "boss", "admin-pass-8")
    me = (await client.get("/api/v1/auth/me", headers=_auth(token))).json()["data"]
    for body in ({"is_active": False}, {"role_code": "member"}):
        resp = await client.patch(f"/api/v1/users/{me['id']}", headers=_auth(token), json=body)
        assert resp.status_code == 400, body
    # 未被改动：仍能访问 admin 路由
    assert (await client.get("/api/v1/users", headers=_auth(token))).status_code == 200


async def test_validation_error_unified_format(client: AsyncClient) -> None:
    """422 校验错误也走统一 {code,msg,data}。"""
    resp = await client.post("/api/v1/auth/login", json={"username": ""})
    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == 422 and "data" in body and "msg" in body


async def test_not_found_unified_format(client: AsyncClient) -> None:
    """404 也走统一 {code,msg,data}。"""
    resp = await client.get("/api/v1/does-not-exist")
    assert resp.status_code == 404
    assert set(resp.json().keys()) == {"code", "msg", "data"}


async def test_overlong_password_rejected(client: AsyncClient) -> None:
    """>72 字节密码返回统一 400 而非 500。"""
    token = await _login(client, "boss", "admin-pass-8")
    resp = await client.post(
        "/api/v1/users",
        headers=_auth(token),
        json={"username": "longpw", "password": "汉" * 25},  # 75 字节
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == 400


async def test_admin_feishu_binding_is_authorized_unique_and_updatable(
    client: AsyncClient,
) -> None:
    admin_token = await _login(client, "boss", "admin-pass-8")
    member_token = await _login(client, "staff", "member-pass-8")

    denied = await client.get("/api/v1/users", headers=_auth(member_token))
    assert denied.status_code == 403

    created = await client.post(
        "/api/v1/users",
        headers=_auth(admin_token),
        json={
            "username": "feishu01",
            "password": "feishu-pass-88",
            "feishu_open_id": "ou_admin_bound_123456",
        },
    )
    assert created.status_code == 200, created.text
    user_id = created.json()["data"]["id"]
    assert created.json()["data"]["feishu_open_id"] == "ou_admin_bound_123456"

    duplicate = await client.post(
        "/api/v1/users",
        headers=_auth(admin_token),
        json={
            "username": "feishu02",
            "password": "feishu-pass-88",
            "feishu_open_id": "ou_admin_bound_123456",
        },
    )
    assert duplicate.status_code == 409

    updated = await client.patch(
        f"/api/v1/users/{user_id}",
        headers=_auth(admin_token),
        json={"feishu_open_id": "ou_admin_updated_123456"},
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["feishu_open_id"] == "ou_admin_updated_123456"

    unbound = await client.patch(
        f"/api/v1/users/{user_id}",
        headers=_auth(admin_token),
        json={"feishu_open_id": None},
    )
    assert unbound.status_code == 200
    assert unbound.json()["data"]["feishu_open_id"] is None
