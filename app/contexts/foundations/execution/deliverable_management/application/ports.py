"""Ports owned by Deliverable Management application policy."""

from __future__ import annotations

import uuid
from typing import Protocol

from app.contexts.foundations.execution.deliverable_management.application.use_cases import (
    PreparedDeliverable,
)
from app.contexts.foundations.execution.deliverable_management.contracts.delivery import (
    DeliverableSnapshot,
    PublishedArtifact,
)


class DeliverableRepository(Protocol):
    async def find_by_idempotency_key(self, key: str) -> DeliverableSnapshot | None: ...

    async def publish(
        self,
        prepared: PreparedDeliverable,
        storage_path: str,
    ) -> PublishedArtifact: ...

    async def get(self, deliverable_id: uuid.UUID) -> DeliverableSnapshot | None: ...

    async def list_for(
        self,
        owner_user_id: uuid.UUID,
        *,
        limit: int,
    ) -> tuple[DeliverableSnapshot, ...]: ...


class ArtifactStorage(Protocol):
    async def put(
        self,
        object_name: str,
        data: bytes,
        content_type: str,
    ) -> str: ...
