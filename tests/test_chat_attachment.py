"""群聊附件上传/下载单测（I6，docs/18）:MinIO 打桩，验证元数据 + 越权路径拦截。"""

import io
import uuid
from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import get_db
from app.main import app
from app.models import Base
from app.models.discussion import DiscussionMessage
from app.models.system import SysUser
from app.services import discussion_service


@pytest.fixture
async def client(monkeypatch: pytest.MonkeyPatch) -> AsyncGenerator[AsyncClient, None]:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        user = SysUser(id=uuid.uuid4(), username="u", password_hash="x", role_code="member")
        other = SysUser(id=uuid.uuid4(), username="other", password_hash="x", role_code="member")
        s.add_all([user, other])
        await s.commit()
        own_channel = await discussion_service.create_channel(s, name="mine", creator_id=user.id)
        other_channel = await discussion_service.create_channel(
            s, name="other", creator_id=other.id
        )
        s.add_all(
            [
                DiscussionMessage(
                    channel_id=own_channel.id,
                    speaker_type="human",
                    speaker_id=user.id,
                    speaker_name="u",
                    content="mine",
                    attachments=[
                        {
                            "type": "image",
                            "name": "photo.png",
                            "storage_path": "youdoo/chat/abc/photo.png",
                            "size": 10,
                        }
                    ],
                ),
                DiscussionMessage(
                    channel_id=other_channel.id,
                    speaker_type="human",
                    speaker_id=other.id,
                    speaker_name="other",
                    content="private",
                    attachments=[
                        {
                            "type": "file",
                            "name": "private.pdf",
                            "storage_path": "youdoo/chat/private/private.pdf",
                            "size": 20,
                        }
                    ],
                ),
            ]
        )
        await s.commit()

    async def _override() -> AsyncGenerator[AsyncSession, None]:
        async with maker() as s:
            yield s

    # 打桩鉴权：任意请求视作已登录 user
    from app.api import deps

    async def _fake_user() -> SysUser:
        async with maker() as s:
            user = (await s.execute(__import__("sqlalchemy").select(SysUser))).scalars().first()
            assert user is not None
            return user

    app.dependency_overrides[get_db] = _override
    app.dependency_overrides[deps.get_current_user] = _fake_user
    # 打桩 MinIO
    from app.knowledge import storage

    async def _put(object_name: str, data: bytes, ct: str = "") -> str:
        return f"youdoo/{object_name}"

    async def _get(object_name: str) -> bytes:
        return b"filecontent"

    monkeypatch.setattr(storage, "put_object", _put)
    monkeypatch.setattr(storage, "get_object_bytes", _get)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c
    app.dependency_overrides.clear()
    await engine.dispose()


async def test_upload_returns_metadata(client: AsyncClient) -> None:
    """上传图片 → 返回 type=image + storage_path + size。"""
    files = {"file": ("photo.png", io.BytesIO(b"x" * 100), "image/png")}
    r = await client.post("/api/v1/channels/attachments", files=files)
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["type"] == "image" and data["name"] == "photo.png" and data["size"] == 100
    assert data["storage_path"].startswith("youdoo/chat/")


async def test_upload_file_type(client: AsyncClient) -> None:
    files = {"file": ("doc.pdf", io.BytesIO(b"y" * 50), "application/pdf")}
    r = await client.post("/api/v1/channels/attachments", files=files)
    assert r.json()["data"]["type"] == "file"


async def test_upload_rejects_file_over_20mb(client: AsyncClient) -> None:
    files = {
        "file": (
            "large.bin",
            io.BytesIO(b"x" * (20 * 1024 * 1024 + 1)),
            "application/octet-stream",
        )
    }
    response = await client.post("/api/v1/channels/attachments", files=files)
    assert response.status_code == 400
    assert "20MB" in response.json()["msg"]


async def test_download_rejects_non_chat_path(client: AsyncClient) -> None:
    """越权:下载非 chat/ 前缀的对象 → 400（防读任意 MinIO 对象）。"""
    r = await client.get(
        "/api/v1/channels/attachments/download",
        params={"storage_path": "youdoo/secret/x", "name": "x"},
    )
    assert r.status_code == 400


async def test_download_chat_attachment(client: AsyncClient) -> None:
    r = await client.get(
        "/api/v1/channels/attachments/download",
        params={"storage_path": "youdoo/chat/abc/photo.png", "name": "photo.png"},
    )
    assert r.status_code == 200 and r.content == b"filecontent"


async def test_download_rejects_unattached_chat_object(client: AsyncClient) -> None:
    """仅有 chat/ 前缀但未挂到消息的对象不可下载。"""
    r = await client.get(
        "/api/v1/channels/attachments/download",
        params={"storage_path": "youdoo/chat/orphan/file.pdf", "name": "file.pdf"},
    )
    assert r.status_code == 403


async def test_download_rejects_other_channel_attachment(client: AsyncClient) -> None:
    """附件存在于消息中，但当前用户不是该群成员时仍不可下载。"""
    r = await client.get(
        "/api/v1/channels/attachments/download",
        params={
            "storage_path": "youdoo/chat/private/private.pdf",
            "name": "private.pdf",
        },
    )
    assert r.status_code == 403
