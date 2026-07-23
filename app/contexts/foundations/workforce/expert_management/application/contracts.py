"""Expert Management commands containing only stable scalar data."""

from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CreateExpertCommand:
    name: str
    prompt_template: str
    duty: str | None = None
    model_role: str = "daily"
    department_id: uuid.UUID | None = None
    permission_scope_json: str = "{}"
    tools_json: str = "[]"
    tier: str = "member"
    title: str = ""
    report_to_id: uuid.UUID | None = None
    owner_user_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class SeedExpertCommand:
    """Idempotent company-template profile identified by a stable code."""

    code: str
    name: str
    prompt_template: str
    title: str
    tier: str
    model_role: str
    department_id: uuid.UUID | None
    duty: str | None = None
    report_to_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class UpdateExpertCommand:
    expert_id: uuid.UUID
    name: str | None = None
    prompt_template: str | None = None
    duty: str | None = None
    model_role: str | None = None
    is_active: bool | None = None
    permission_scope_json: str | None = None
    tools_json: str | None = None
    title: str | None = None
    tier: str | None = None
    report_to_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
