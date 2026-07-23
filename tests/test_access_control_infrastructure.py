"""Access Control persistence compatibility over the existing grant table."""

import uuid
from collections.abc import AsyncGenerator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.contexts.foundations.access_control.entrypoints import operations as access
from app.contexts.shared_kernel import ResourceNotFound
from app.models import Base
from app.models.resource_grant import ResourceGrant


@pytest.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def test_create_list_and_revoke_reuse_resource_grant_table(db: AsyncSession) -> None:
    resource_id = uuid.uuid4()
    grantee_id = uuid.uuid4()

    created = await access.create_grant(
        db,
        resource_type="data_source",
        resource_id=resource_id,
        grantee_type="user",
        grantee_id=grantee_id,
        permission="write",
        granted_by=None,
    )
    persisted = await db.get(ResourceGrant, created.id)
    listed = await access.list_grants(
        db,
        resource_type="data_source",
        grantee_id=None,
    )

    assert persisted is not None and persisted.perm == "write"
    assert listed == (created,)

    await access.revoke_grant(db, created.id)
    assert (await db.get(ResourceGrant, created.id)).is_delete  # type: ignore[union-attr]
    with pytest.raises(ResourceNotFound, match="授权记录不存在"):
        await access.get_grant(db, created.id)
