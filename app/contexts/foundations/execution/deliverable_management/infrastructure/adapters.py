"""SQLAlchemy persistence and object-storage adapters."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.execution.deliverable_management.application.use_cases import (
    PreparedDeliverable,
)
from app.contexts.foundations.execution.deliverable_management.contracts.delivery import (
    DeliverableFormat,
    DeliverableSnapshot,
    PublishedArtifact,
)
from app.models.deliverable import Deliverable

ObjectPut = Callable[[str, bytes, str], Awaitable[str]]


def _snapshot(row: Deliverable) -> DeliverableSnapshot:
    return DeliverableSnapshot(
        deliverable_id=row.id,
        owner_user_id=row.owner_user_id,
        agent_name=row.agent_name,
        file_name=row.file_name,
        file_format=DeliverableFormat(row.file_format),
        storage_path=row.storage_path,
        file_size=row.file_size,
        create_time=row.create_time,
        is_deleted=row.is_delete,
    )


def _artifact(row: Deliverable) -> PublishedArtifact:
    return PublishedArtifact(
        deliverable_id=row.id,
        file_name=row.file_name,
        file_format=DeliverableFormat(row.file_format),
        storage_path=row.storage_path,
        file_size=row.file_size,
        agent_name=row.agent_name,
    )


class SQLAlchemyDeliverableRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_by_idempotency_key(self, key: str) -> DeliverableSnapshot | None:
        row = (
            await self._session.execute(
                select(Deliverable).where(Deliverable.idempotency_key == key)
            )
        ).scalar_one_or_none()
        return _snapshot(row) if row is not None else None

    async def publish(
        self,
        prepared: PreparedDeliverable,
        storage_path: str,
    ) -> PublishedArtifact:
        row = None
        if prepared.idempotency_key:
            row = (
                await self._session.execute(
                    select(Deliverable).where(
                        Deliverable.idempotency_key == prepared.idempotency_key
                    )
                )
            ).scalar_one_or_none()
        if row is None:
            row = await self._session.get(Deliverable, prepared.deliverable_id)
        if row is None:
            row = Deliverable(id=prepared.deliverable_id)
            self._session.add(row)
        row.owner_user_id = prepared.owner_user_id
        row.agent_id = prepared.agent_id
        row.agent_name = prepared.agent_name
        row.file_name = prepared.file_name
        row.file_format = prepared.file_format.value
        row.storage_path = storage_path
        row.file_size = len(prepared.data)
        row.idempotency_key = prepared.idempotency_key
        try:
            await self._session.commit()
            await self._session.refresh(row)
            return _artifact(row)
        except IntegrityError:
            await self._session.rollback()
            if prepared.idempotency_key:
                concurrent = await self.find_by_idempotency_key(prepared.idempotency_key)
                if concurrent is not None:
                    return PublishedArtifact(
                        deliverable_id=concurrent.deliverable_id,
                        file_name=concurrent.file_name,
                        file_format=concurrent.file_format,
                        storage_path=concurrent.storage_path,
                        file_size=concurrent.file_size,
                        agent_name=concurrent.agent_name,
                    )
            raise
        except Exception:
            await self._session.rollback()
            raise

    async def get(self, deliverable_id: uuid.UUID) -> DeliverableSnapshot | None:
        row = await self._session.get(Deliverable, deliverable_id)
        return _snapshot(row) if row is not None else None

    async def list_for(
        self,
        owner_user_id: uuid.UUID,
        *,
        limit: int,
    ) -> tuple[DeliverableSnapshot, ...]:
        rows = (
            await self._session.execute(
                select(Deliverable)
                .where(
                    Deliverable.owner_user_id == owner_user_id,
                    Deliverable.is_delete.is_(False),
                )
                .order_by(Deliverable.create_time.desc())
                .limit(limit)
            )
        ).scalars()
        return tuple(_snapshot(row) for row in rows)


class ObjectStorageAdapter:
    def __init__(self, put_object: ObjectPut) -> None:
        self._put_object = put_object

    async def put(
        self,
        object_name: str,
        data: bytes,
        content_type: str,
    ) -> str:
        return await self._put_object(object_name, data, content_type)
