"""Tests for the fixed-target offline Feishu support binding helper."""

from collections.abc import AsyncGenerator

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.exceptions import AppError
from app.models import Base
from app.models.system import SysUser
from app.services.feishu_login import FeishuLoginService
from app.services.feishu_support import bind_captured_denied_identity_to_zoey


class CaptureOnlyStore:
    """Minimal one-slot store used by the bounded support helper tests."""

    def __init__(self) -> None:
        self.open_id: str | None = None

    async def save_denied_identity(self, open_id: str, ttl: int) -> bool:
        if self.open_id is not None:
            return False
        self.open_id = open_id
        return True

    async def consume_denied_identity(self) -> str | None:
        open_id = self.open_id
        self.open_id = None
        return open_id

    async def close(self) -> None:
        return None


@pytest.fixture
async def db_factory() -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


def make_capture_service() -> tuple[FeishuLoginService, CaptureOnlyStore]:
    store = CaptureOnlyStore()
    service = FeishuLoginService(store)  # type: ignore[arg-type]
    return service, store


async def test_support_helper_consumes_capture_and_binds_only_zoey(
    db_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_factory() as db:
        db.add(SysUser(username="zoey", password_hash="unused", role_code="member"))
        await db.commit()

    service, _ = make_capture_service()
    assert await service.capture_denied_identity("ou_zoey_denied_123456") is True

    async with db_factory() as db:
        user = await bind_captured_denied_identity_to_zoey(db, service)

    assert user.username == "zoey"
    assert user.feishu_open_id == "ou_zoey_denied_123456"
    assert await service.consume_captured_denied_identity() is None


@pytest.mark.parametrize("target_state", ["missing", "disabled", "deleted", "already_bound"])
async def test_support_helper_safe_target_failures_do_not_consume_capture(
    db_factory: async_sessionmaker[AsyncSession], target_state: str
) -> None:
    if target_state != "missing":
        user = SysUser(username="zoey", password_hash="unused", role_code="member")
        if target_state == "disabled":
            user.is_active = False
        elif target_state == "deleted":
            user.is_delete = True
        elif target_state == "already_bound":
            user.feishu_open_id = "ou_existing_123456"
        async with db_factory() as db:
            db.add(user)
            await db.commit()

    service, _ = make_capture_service()
    assert await service.capture_denied_identity("ou_pending_123456") is True

    async with db_factory() as db:
        with pytest.raises(AppError):
            await bind_captured_denied_identity_to_zoey(db, service)

    assert await service.consume_captured_denied_identity() == "ou_pending_123456"


async def test_support_helper_consumes_capture_on_uniqueness_failure(
    db_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_factory() as db:
        db.add_all(
            [
                SysUser(username="zoey", password_hash="unused", role_code="member"),
                SysUser(
                    username="other",
                    password_hash="unused",
                    role_code="member",
                    feishu_open_id="ou_conflict_123456",
                ),
            ]
        )
        await db.commit()

    service, _ = make_capture_service()
    assert await service.capture_denied_identity("ou_conflict_123456") is True

    async with db_factory() as db:
        with pytest.raises(AppError) as caught:
            await bind_captured_denied_identity_to_zoey(db, service)

    assert caught.value.status_code == 409
    assert await service.consume_captured_denied_identity() is None
    async with db_factory() as db:
        zoey = (
            await db.execute(select(SysUser).where(SysUser.username == "zoey"))
        ).scalar_one()
        assert zoey.feishu_open_id is None
