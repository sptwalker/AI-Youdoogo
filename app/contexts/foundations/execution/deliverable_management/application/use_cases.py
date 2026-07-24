"""Create and publish Deliverable artifacts."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.contexts.foundations.execution.deliverable_management.application.formatting import (
    CONTENT_TYPES,
    build_bytes,
    object_name,
    safe_file_name,
)
from app.contexts.foundations.execution.deliverable_management.contracts.delivery import (
    DeliverableFormat,
    PublishDeliverableCommand,
    PublishedArtifact,
)

if TYPE_CHECKING:
    from app.contexts.foundations.execution.deliverable_management.application.ports import (
        ArtifactStorage,
        DeliverableRepository,
    )


@dataclass(frozen=True, slots=True)
class PreparedDeliverable:
    deliverable_id: uuid.UUID
    owner_user_id: uuid.UUID
    agent_id: uuid.UUID | None
    agent_name: str
    file_name: str
    file_format: DeliverableFormat
    data: bytes
    content_type: str
    object_name: str
    idempotency_key: str | None


class CreateDeliverable:
    """Validate and render a delivery before any external side effect occurs."""

    def __init__(self, repository: DeliverableRepository) -> None:
        self._repository = repository

    async def execute(self, command: PublishDeliverableCommand) -> PreparedDeliverable:
        existing = None
        if command.idempotency_key:
            existing = await self._repository.find_by_idempotency_key(
                command.idempotency_key
            )
        deliverable_id = existing.deliverable_id if existing else uuid.uuid4()
        file_name = safe_file_name(command.name, command.file_format)
        data = build_bytes(command.file_format, command.body)
        return PreparedDeliverable(
            deliverable_id=deliverable_id,
            owner_user_id=command.owner_user_id,
            agent_id=command.agent_id,
            agent_name=command.agent_name,
            file_name=file_name,
            file_format=command.file_format,
            data=data,
            content_type=CONTENT_TYPES[command.file_format],
            object_name=object_name(
                deliverable_id,
                file_name,
                command.idempotency_key,
            ),
            idempotency_key=command.idempotency_key,
        )


class PublishArtifact:
    """Upload first, then publish the database record as the visible success point."""

    def __init__(
        self,
        repository: DeliverableRepository,
        storage: ArtifactStorage,
    ) -> None:
        self._repository = repository
        self._storage = storage

    async def execute(self, prepared: PreparedDeliverable) -> PublishedArtifact:
        storage_path = await self._storage.put(
            prepared.object_name,
            prepared.data,
            prepared.content_type,
        )
        return await self._repository.publish(prepared, storage_path)
