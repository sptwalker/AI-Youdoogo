"""Pure review requests and decisions; never source-aggregate state."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import StrEnum


class ReviewRisk(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True, slots=True)
class ReviewRequest:
    action: str
    target_type: str
    target_id: str
    principal_id: uuid.UUID | None
    risk: ReviewRisk
    payload_hash: str | None = None
    policy_version: str | None = None
    approval_reference: str | None = None


@dataclass(frozen=True, slots=True)
class ReviewDecision:
    approved: bool
    requires_human: bool
    reason: str = ""
    decision_reference: str | None = None
