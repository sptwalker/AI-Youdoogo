"""Owned Collaboration Request state and transition rules."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from app.contexts.business.collaboration_requests.domain.errors import (
    CollaborationReviewNotAllowed,
    InvalidReviewDecision,
)

PENDING = "pending"
APPROVED = "approved"
REJECTED = "rejected"
LOW_RISK = "low"
HIGH_RISK = "high"

HIGH_RISK_CATEGORIES = frozenset(
    {"finance", "budget", "hr", "project", "major_change"}
)


def classify_risk(category: str | None) -> str:
    """Classify red-line work as high risk; draft-only work remains low risk."""
    return HIGH_RISK if category in HIGH_RISK_CATEGORIES else LOW_RISK


@dataclass(slots=True)
class CollaborationAuthorization:
    id: uuid.UUID
    source_department_id: uuid.UUID
    target_department_id: uuid.UUID
    collab_type: str
    authorized_by: uuid.UUID | None
    is_active: bool
    create_time: datetime
    is_deleted: bool = False

    def revoke(self) -> None:
        self.is_deleted = True


@dataclass(slots=True)
class CollaborationRequest:
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

    def review(
        self,
        *,
        decision: str,
        reviewer_id: uuid.UUID,
        note: str | None,
    ) -> None:
        if decision not in ("approve", "reject"):
            raise InvalidReviewDecision()
        if self.status != PENDING:
            raise CollaborationReviewNotAllowed(self.status)
        self.status = APPROVED if decision == "approve" else REJECTED
        self.reviewed_by = reviewer_id
        self.review_note = note
