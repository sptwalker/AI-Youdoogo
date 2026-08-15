"""Caller-owned ports required by Work Desktop."""

from __future__ import annotations

import uuid
from typing import Protocol

from app.contexts.business.work_desktop.application.contracts import (
    CollaborationProjection,
    DeliverableProjection,
    DesktopPrincipal,
    InboxItemRef,
    InboxStateProjection,
    ProposalProjection,
    ResolutionProjection,
    TaskProjection,
)


class TaskDashboardPort(Protocol):
    async def reported_for(
        self, principal: DesktopPrincipal, *, limit: int
    ) -> tuple[TaskProjection, ...]: ...

    async def active_for(
        self, principal: DesktopPrincipal, *, limit: int
    ) -> tuple[TaskProjection, ...]: ...


class ProposalQueuePort(Protocol):
    async def reviewed(self, *, limit: int) -> tuple[ProposalProjection, ...]: ...


class ResolutionQueuePort(Protocol):
    async def unconfirmed(self, *, limit: int) -> tuple[ResolutionProjection, ...]: ...


class CollaborationQueuePort(Protocol):
    async def review_queue(
        self, principal: DesktopPrincipal
    ) -> tuple[CollaborationProjection, ...]: ...


class ChannelCounterPort(Protocol):
    async def count(self) -> int: ...


class KnowledgeCounterPort(Protocol):
    async def count_for(self, principal: DesktopPrincipal) -> int: ...


class IdentityDirectoryPort(Protocol):
    async def get(self, user_id: uuid.UUID) -> DesktopPrincipal | None: ...


class DeliverableInboxPort(Protocol):
    async def list_for(
        self, owner_user_id: uuid.UUID, *, limit: int
    ) -> tuple[DeliverableProjection, ...]: ...

    async def get(self, deliverable_id: uuid.UUID) -> DeliverableProjection | None: ...


class ObjectStoragePort(Protocol):
    async def get_object_bytes(self, object_name: str) -> bytes: ...


class InboxStatePort(Protocol):
    async def states_for(
        self, owner_user_id: uuid.UUID
    ) -> dict[tuple[str, uuid.UUID], InboxStateProjection]:
        """本人全部收件箱读态，键为 (kind, source_id)。"""
        ...

    async def mark(
        self,
        owner_user_id: uuid.UUID,
        items: tuple[InboxItemRef, ...],
        *,
        is_read: bool | None = None,
        is_processed: bool | None = None,
    ) -> int:
        """批量置读态（upsert，仅改本人行）；返回受影响条目数。"""
        ...
