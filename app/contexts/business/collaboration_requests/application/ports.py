"""Persistence and transaction ports owned by Collaboration Requests."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, Self

from app.contexts.business.collaboration_requests.domain.models import (
    CollaborationAuthorization,
    CollaborationRequest,
)


class CollaborationRepository(Protocol):
    async def add_authorization(self, authorization: CollaborationAuthorization) -> None: ...

    async def get_authorization(
        self, authorization_id: uuid.UUID
    ) -> CollaborationAuthorization | None: ...

    async def save_authorization(self, authorization: CollaborationAuthorization) -> None: ...

    async def list_authorizations(
        self, *, target_department_id: uuid.UUID | None
    ) -> list[CollaborationAuthorization]: ...

    async def has_authorization(
        self,
        *,
        source_department_id: uuid.UUID,
        target_department_id: uuid.UUID,
        collab_type: str,
    ) -> bool: ...

    async def add_request(self, request: CollaborationRequest) -> None: ...

    async def get_request(self, request_id: uuid.UUID) -> CollaborationRequest | None: ...

    async def get_request_by_idempotency_key(
        self, idempotency_key: str
    ) -> CollaborationRequest | None: ...

    async def save_request(self, request: CollaborationRequest) -> None: ...

    async def list_pending_requests(
        self, *, target_department_ids: tuple[uuid.UUID, ...] | None
    ) -> list[CollaborationRequest]: ...


class CollaborationUnitOfWork(Protocol):
    @property
    def collaborations(self) -> CollaborationRepository: ...

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object | None,
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


CollaborationUnitOfWorkFactory = Callable[[], CollaborationUnitOfWork]


class ReviewScopePort(Protocol):
    async def reviewable_department_ids(
        self, *, supervisor_user_id: uuid.UUID, is_admin: bool
    ) -> tuple[uuid.UUID, ...] | None: ...

    async def can_review(
        self,
        *,
        reviewer_id: uuid.UUID,
        target_department_id: uuid.UUID,
        is_admin: bool,
    ) -> bool: ...


@dataclass(frozen=True, slots=True)
class AuditRequest:
    actor_id: uuid.UUID | None
    actor_role: str | None
    action: str
    summary: str
    target_type: str
    target_id: uuid.UUID


class AuditPort(Protocol):
    async def record(self, request: AuditRequest) -> None: ...


class Clock(Protocol):
    def now(self) -> datetime: ...


class IdentifierPort(Protocol):
    def new_id(self) -> uuid.UUID: ...
