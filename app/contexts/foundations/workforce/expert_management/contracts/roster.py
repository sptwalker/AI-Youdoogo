"""Immutable Expert roster snapshots for organization and UI consumers."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class ExpertRosterSnapshot:
    """Versioned expert profile without ORM or mutable JSON objects."""

    expert_id: uuid.UUID
    version: str
    code: str | None
    name: str
    title: str
    tier: str
    department_id: uuid.UUID | None
    report_to_id: uuid.UUID | None
    owner_user_id: uuid.UUID | None
    duty: str | None
    prompt_template: str
    model_role: str
    permission_scope_json: str
    tools_json: str
    is_seed: bool
    is_active: bool
    create_time: datetime


@dataclass(frozen=True, slots=True)
class DepartmentExpertCount:
    department_id: uuid.UUID
    count: int
