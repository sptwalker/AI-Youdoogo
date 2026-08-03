"""Characterize legacy Identity persistence and partial-update semantics."""

import uuid
from collections.abc import AsyncGenerator

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.contexts.foundations.identity.entrypoints import operations as identity
from app.models import Base
from app.models.system import SysUser
from app.platform.outbox.model import OutboxEvent


@pytest.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def test_create_user_commits_identity_and_source_change_together(
    db: AsyncSession,
) -> None:
    user = await identity.create_user(
        db,
        username="identity01",
        password="identity-pass-88",
        real_name="身份用户",
        role_code="member",
        department_id=None,
        feishu_open_id=None,
    )

    persisted = await db.get(SysUser, user.id)
    event = (
        await db.execute(
            select(OutboxEvent).where(
                OutboxEvent.aggregate_id == user.id,
                OutboxEvent.event_type == "environment.source.changed.v1",
            )
        )
    ).scalar_one()
    assert persisted is not None and persisted.username == "identity01"
    assert event.payload["source_type"] == "identity"
    assert event.payload["source_id"] == str(user.id)


async def test_resolve_user_includes_inactive_but_excludes_soft_deleted(
    db: AsyncSession,
) -> None:
    inactive = SysUser(
        username="inactive",
        password_hash="x",
        role_code="member",
        is_active=False,
    )
    deleted = SysUser(
        username="deleted",
        password_hash="x",
        role_code="member",
        is_delete=True,
    )
    db.add_all([inactive, deleted])
    await db.commit()

    assert await identity.get_user_by_id(db, user_id=inactive.id) is not None
    assert await identity.get_user_by_id(db, user_id=deleted.id) is None


async def test_partial_update_preserves_department_but_explicitly_unbinds_feishu(
    db: AsyncSession,
) -> None:
    department_id = uuid.uuid4()
    user = SysUser(
        username="partial",
        password_hash="x",
        role_code="member",
        department_id=department_id,
        feishu_open_id="ou_partial_123456",
    )
    db.add(user)
    await db.commit()

    updated = await identity.update_user(
        db,
        user_id=user.id,
        password=None,
        real_name=None,
        role_code=None,
        department_id=None,
        is_active=None,
        feishu_open_id=None,
        feishu_binding_changed=True,
    )

    assert updated.department_id == department_id
    assert updated.feishu_open_id is None
