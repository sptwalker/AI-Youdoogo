"""群聊 API 权限回归：成员隔离、群主操作与管理视图。"""

import uuid
from collections.abc import AsyncGenerator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api import deps
from app.core.database import get_db
from app.main import app
from app.models import Base
from app.models.discussion import DiscussionMessage
from app.models.system import SysUser
from app.services import discussion_service

PermissionContext = tuple[AsyncClient, dict[str, uuid.UUID], dict[str, uuid.UUID]]


@pytest.fixture
async def permission_ctx() -> AsyncGenerator[PermissionContext, None]:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    roles = ("owner", "member", "outsider", "admin", "executive")
    user_ids = {role: uuid.uuid4() for role in roles}
    async with maker() as db:
        db.add_all(
            [
                SysUser(
                    id=user_id,
                    username=role,
                    password_hash="x",
                    role_code=role if role in {"admin", "executive"} else "member",
                )
                for role, user_id in user_ids.items()
            ]
        )
        await db.commit()
        private = await discussion_service.create_channel(
            db,
            name="owner-private",
            creator_id=user_ids["owner"],
            members=[{"member_type": "human", "member_id": user_ids["member"]}],
        )
        outsider_private = await discussion_service.create_channel(
            db, name="outsider-private", creator_id=user_ids["outsider"]
        )
        db.add(
            DiscussionMessage(
                channel_id=private.id,
                speaker_type="human",
                speaker_id=user_ids["owner"],
                speaker_name="owner",
                content="private message",
            )
        )
        await db.commit()

    state = {
        "user_id": user_ids["outsider"],
        "private": private.id,
        "outsider_private": outsider_private.id,
    }

    async def _override_db() -> AsyncGenerator[AsyncSession, None]:
        async with maker() as db:
            yield db

    async def _fake_user() -> SysUser:
        async with maker() as db:
            user = await db.get(SysUser, state["user_id"])
            assert user is not None
            return user

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[deps.get_current_user] = _fake_user
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, user_ids, state
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.parametrize(
    ("method", "path_suffix", "request_kwargs"),
    [
        ("GET", "/members", {}),
        ("GET", "/messages", {}),
        ("POST", "/read", {}),
        ("POST", "/messages", {"json": {"content": "intrude", "mentioned_agent_ids": []}}),
    ],
)
async def test_non_member_cannot_access_channel_resources(
    permission_ctx: PermissionContext,
    method: str,
    path_suffix: str,
    request_kwargs: dict[str, Any],
) -> None:
    client, _, state = permission_ctx
    response = await client.request(
        method,
        f"/api/v1/channels/{state['private']}{path_suffix}",
        **request_kwargs,
    )
    assert response.status_code == 403
    assert response.json()["code"] == 403


async def test_only_owner_can_add_members(permission_ctx: PermissionContext) -> None:
    client, users, state = permission_ctx
    state["user_id"] = users["member"]
    body = {"members": [{"member_type": "human", "member_id": str(users["outsider"])}]}
    denied = await client.post(f"/api/v1/channels/{state['private']}/members", json=body)
    assert denied.status_code == 403

    state["user_id"] = users["owner"]
    allowed = await client.post(f"/api/v1/channels/{state['private']}/members", json=body)
    assert allowed.status_code == 200
    assert allowed.json()["data"] == {"added": 1}


async def test_owner_cannot_be_removed(permission_ctx: PermissionContext) -> None:
    client, users, state = permission_ctx
    state["user_id"] = users["owner"]
    response = await client.delete(
        f"/api/v1/channels/{state['private']}/members/human/{users['owner']}"
    )
    assert response.status_code == 400
    assert response.json()["code"] == 400


async def test_channel_list_is_member_scoped_but_managers_see_all(
    permission_ctx: PermissionContext,
) -> None:
    client, users, state = permission_ctx
    state["user_id"] = users["owner"]
    owner_rows = (await client.get("/api/v1/channels")).json()["data"]
    assert {row["id"] for row in owner_rows} == {str(state["private"])}

    for manager_role in ("admin", "executive"):
        state["user_id"] = users[manager_role]
        response = await client.get("/api/v1/channels")
        assert response.status_code == 200
        assert {row["id"] for row in response.json()["data"]} == {
            str(state["private"]),
            str(state["outsider_private"]),
        }


async def test_member_keeps_read_contract(permission_ctx: PermissionContext) -> None:
    client, users, state = permission_ctx
    state["user_id"] = users["member"]
    members = await client.get(f"/api/v1/channels/{state['private']}/members")
    messages = await client.get(f"/api/v1/channels/{state['private']}/messages")
    read = await client.post(f"/api/v1/channels/{state['private']}/read")
    assert members.status_code == messages.status_code == read.status_code == 200
    assert messages.json()["data"][0]["content"] == "private message"
