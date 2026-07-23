"""Plain commands, queries, and results for Collaboration Requests."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class AuthorizeCollaborationCommand:
    source_department_id: uuid.UUID
    target_department_id: uuid.UUID
    collab_type: str
    authorized_by: uuid.UUID | None
    actor_role: str | None = None


@dataclass(frozen=True, slots=True)
class RevokeCollaborationAuthorizationCommand:
    authorization_id: uuid.UUID
    actor_id: uuid.UUID | None = None
    actor_role: str | None = None


@dataclass(frozen=True, slots=True)
class ListCollaborationAuthorizationsQuery:
    target_department_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class HasCollaborationAuthorizationQuery:
    source_department_id: uuid.UUID
    target_department_id: uuid.UUID
    collab_type: str


@dataclass(frozen=True, slots=True)
class CreateCollaborationRequestCommand:
    target_department_id: uuid.UUID
    title: str
    source_department_id: uuid.UUID | None = None
    summary: str | None = None
    category: str | None = None
    risk_level: str | None = None
    requested_by: uuid.UUID | None = None
    idempotency_key: str | None = None


@dataclass(frozen=True, slots=True)
class CollaborationReviewQueueQuery:
    supervisor_user_id: uuid.UUID
    is_admin: bool = False


@dataclass(frozen=True, slots=True)
class ReviewCollaborationRequestCommand:
    request_id: uuid.UUID
    decision: str
    reviewer_id: uuid.UUID
    note: str | None = None
    actor_role: str | None = None


@dataclass(frozen=True, slots=True)
class CollaborationReviewPrincipal:
    id: uuid.UUID
    role_code: str


@dataclass(frozen=True, slots=True)
class CollaborationAuthorizationResult:
    id: uuid.UUID
    source_department_id: uuid.UUID
    target_department_id: uuid.UUID
    collab_type: str
    authorized_by: uuid.UUID | None
    is_active: bool
    create_time: datetime


@dataclass(frozen=True, slots=True)
class CollaborationRequestResult:
    id: uuid.UUID
    source_department_id: uuid.UUID | None
    target_department_id: uuid.UUID
    title: str
    summary: str | None
    category: str | None
    risk_level: str
    status: str
    requested_by: uuid.UUID | None
    reviewed_by: uuid.UUID | None
    review_note: str | None
    ref_type: str | None
    ref_id: uuid.UUID | None
    idempotency_key: str | None
    create_time: datetime
