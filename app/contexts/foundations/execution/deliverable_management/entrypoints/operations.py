"""Request-scoped Deliverable Management operations."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

import app.platform.object_storage.gateway as object_storage
from app.contexts.foundations.execution.deliverable_management.application.use_cases import (
    CreateDeliverable,
    PublishArtifact,
)
from app.contexts.foundations.execution.deliverable_management.contracts.delivery import (
    DeliverableSnapshot,
    PublishDeliverableCommand,
    PublishedArtifact,
)
from app.contexts.foundations.execution.deliverable_management.infrastructure.adapters import (
    ObjectPut,
    ObjectStorageAdapter,
    SQLAlchemyDeliverableRepository,
)


async def publish_deliverable(
    session: AsyncSession,
    command: PublishDeliverableCommand,
    *,
    publisher: ObjectPut | None = None,
) -> PublishedArtifact:
    repository = SQLAlchemyDeliverableRepository(session)
    prepared = await CreateDeliverable(repository).execute(command)
    return await PublishArtifact(
        repository,
        ObjectStorageAdapter(publisher or object_storage.put_object),
    ).execute(prepared)


async def get_deliverable(
    session: AsyncSession,
    deliverable_id: uuid.UUID,
) -> DeliverableSnapshot | None:
    return await SQLAlchemyDeliverableRepository(session).get(deliverable_id)


async def list_deliverables(
    session: AsyncSession,
    owner_user_id: uuid.UUID,
    *,
    limit: int = 50,
) -> tuple[DeliverableSnapshot, ...]:
    return await SQLAlchemyDeliverableRepository(session).list_for(
        owner_user_id,
        limit=limit,
    )
