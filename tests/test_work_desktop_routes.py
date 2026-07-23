"""Work Desktop HTTP characterization tests."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from typing import Any
from urllib.parse import quote

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api import deps
from app.contexts.business.work_desktop.infrastructure import adapters
from app.core.database import get_db
from app.main import app
from app.models import Base
from app.models.deliverable import Deliverable
from app.models.system import SysUser
from app.models.task import TaskCard


@pytest.fixture
async def desktop_client(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncGenerator[tuple[AsyncClient, dict[str, Any], dict[str, str]], None]:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    member = SysUser(
        username="member",
        password_hash="x",
        real_name="成员",
        role_code="member",
    )
    other = SysUser(
        username="other",
        password_hash="x",
        real_name="他人",
        role_code="member",
    )
    admin = SysUser(
        username="admin",
        password_hash="x",
        real_name="管理员",
        role_code="admin",
    )
    deleted = SysUser(
        username="deleted",
        password_hash="x",
        role_code="member",
        is_delete=True,
    )
    async with factory() as session:
        session.add_all([member, other, admin, deleted])
        await session.commit()
        session.add_all(
            [
                TaskCard(
                    title="我的待验收",
                    task_type="manual",
                    status="reported",
                    creator_id=member.id,
                ),
                TaskCard(
                    title="他人的待验收",
                    task_type="manual",
                    status="reported",
                    creator_id=other.id,
                ),
            ]
        )
        mine = Deliverable(
            owner_user_id=member.id,
            file_name="我的报告.txt",
            file_format="txt",
            agent_name="助理",
            file_size=4,
            storage_path="bucket/deliverables/mine.txt",
        )
        theirs = Deliverable(
            owner_user_id=other.id,
            file_name="other.txt",
            file_format="txt",
            agent_name="助理",
            file_size=5,
            storage_path="bucket/deliverables/other.txt",
        )
        removed = Deliverable(
            owner_user_id=member.id,
            file_name="removed.txt",
            file_format="txt",
            agent_name="助理",
            file_size=0,
            storage_path="bucket/deliverables/removed.txt",
            is_delete=True,
        )
        session.add_all([mine, theirs, removed])
        await session.commit()

    actor: dict[str, Any] = {"user": member}
    requested: dict[str, str] = {}

    async def _override_db() -> AsyncGenerator[AsyncSession, None]:
        async with factory() as session:
            yield session

    async def _current_user() -> SysUser:
        return actor["user"]

    async def _get_object(object_name: str) -> bytes:
        requested["object_name"] = object_name
        return b"file-body"

    monkeypatch.setattr(adapters, "get_object_bytes", _get_object)
    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[deps.get_current_user] = _current_user
    ids = {
        "member": str(member.id),
        "other": str(other.id),
        "admin": str(admin.id),
        "deleted": str(deleted.id),
        "mine": str(mine.id),
        "theirs": str(theirs.id),
        "removed": str(removed.id),
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield (
            client,
            {"actor": actor, "users": {"member": member, "admin": admin}},
            {
                **ids,
                "requested": requested,  # type: ignore[dict-item]
            },
        )
    app.dependency_overrides.clear()
    await engine.dispose()


async def test_my_desktop_preserves_envelope_and_user_scope(
    desktop_client: tuple[AsyncClient, dict[str, Any], dict[str, Any]],
) -> None:
    client, _, _ = desktop_client
    response = await client.get("/api/v1/desktop")

    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] == 0 and payload["msg"] == "ok"
    assert payload["data"]["user"]["name"] == "成员"
    assert [item["title"] for item in payload["data"]["pending"]] == ["我的待验收"]
    assert payload["data"]["pending_count"] == 1


async def test_supervised_desktop_requires_admin_and_handles_missing_user(
    desktop_client: tuple[AsyncClient, dict[str, Any], dict[str, Any]],
) -> None:
    client, state, ids = desktop_client

    denied = await client.get(f"/api/v1/desktop/{ids['other']}")
    assert denied.status_code == 403

    state["actor"]["user"] = state["users"]["admin"]
    allowed = await client.get(f"/api/v1/desktop/{ids['other']}")
    assert allowed.status_code == 200
    assert allowed.json()["data"]["user"]["name"] == "他人"

    missing = await client.get(f"/api/v1/desktop/{uuid.uuid4()}")
    deleted = await client.get(f"/api/v1/desktop/{ids['deleted']}")
    assert missing.status_code == 404
    assert deleted.status_code == 404


async def test_deliverable_list_owner_and_admin_scope(
    desktop_client: tuple[AsyncClient, dict[str, Any], dict[str, Any]],
) -> None:
    client, state, ids = desktop_client

    mine = await client.get("/api/v1/desktop/deliverables")
    assert mine.status_code == 200
    assert [item["file_name"] for item in mine.json()["data"]] == ["我的报告.txt"]

    denied = await client.get(
        "/api/v1/desktop/deliverables",
        params={"user_id": ids["other"]},
    )
    assert denied.status_code == 403

    state["actor"]["user"] = state["users"]["admin"]
    supervised = await client.get(
        "/api/v1/desktop/deliverables",
        params={"user_id": ids["other"]},
    )
    assert supervised.status_code == 200
    assert [item["file_name"] for item in supervised.json()["data"]] == ["other.txt"]


async def test_download_preserves_storage_key_headers_and_authorization(
    desktop_client: tuple[AsyncClient, dict[str, Any], dict[str, Any]],
) -> None:
    client, state, ids = desktop_client

    response = await client.get(f"/api/v1/desktop/deliverables/{ids['mine']}/download")
    assert response.status_code == 200
    assert response.content == b"file-body"
    assert response.headers["content-type"].startswith("application/octet-stream")
    assert response.headers["content-disposition"] == (
        f"attachment; filename*=UTF-8''{quote('我的报告.txt')}"
    )
    assert ids["requested"]["object_name"] == "deliverables/mine.txt"

    denied = await client.get(f"/api/v1/desktop/deliverables/{ids['theirs']}/download")
    removed = await client.get(f"/api/v1/desktop/deliverables/{ids['removed']}/download")
    missing = await client.get(f"/api/v1/desktop/deliverables/{uuid.uuid4()}/download")
    assert denied.status_code == 403
    assert removed.status_code == 404
    assert missing.status_code == 404

    state["actor"]["user"] = state["users"]["admin"]
    admin_download = await client.get(f"/api/v1/desktop/deliverables/{ids['theirs']}/download")
    assert admin_download.status_code == 200
    assert ids["requested"]["object_name"] == "deliverables/other.txt"
