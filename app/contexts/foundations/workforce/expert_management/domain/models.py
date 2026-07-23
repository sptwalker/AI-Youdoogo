"""Expert profile rules independent from persistence and execution runtime."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from app.contexts.shared_kernel import RuleViolation

VALID_MODEL_ROLES = ("daily", "reasoning")
VALID_TIERS = ("exec", "director", "member")


def validate_model_role(model_role: str) -> None:
    if model_role not in VALID_MODEL_ROLES:
        raise RuleViolation(f"model_role 仅支持 {'/'.join(VALID_MODEL_ROLES)}")


def validate_tier(tier: str) -> None:
    if tier not in VALID_TIERS:
        raise RuleViolation(f"tier 仅支持 {'/'.join(VALID_TIERS)}")


@dataclass(slots=True)
class ExpertProfile:
    id: uuid.UUID
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
    is_deleted: bool = False

    def update(
        self,
        *,
        name: str | None,
        prompt_template: str | None,
        duty: str | None,
        model_role: str | None,
        is_active: bool | None,
        permission_scope_json: str | None,
        tools_json: str | None,
        title: str | None,
        tier: str | None,
        report_to_id: uuid.UUID | None,
        department_id: uuid.UUID | None,
    ) -> None:
        if model_role is not None:
            validate_model_role(model_role)
            self.model_role = model_role
        if tier is not None:
            validate_tier(tier)
            self.tier = tier
        if name is not None:
            self.name = name
        if prompt_template:
            self.prompt_template = prompt_template
        if duty is not None:
            self.duty = duty
        if is_active is not None:
            self.is_active = is_active
        if permission_scope_json is not None:
            self.permission_scope_json = permission_scope_json
        if tools_json is not None:
            self.tools_json = tools_json
        if title is not None:
            self.title = title
        if report_to_id is not None:
            self.report_to_id = report_to_id
        if department_id is not None:
            self.department_id = department_id

    def apply_seed(
        self,
        *,
        code: str,
        name: str,
        title: str,
        tier: str,
        model_role: str,
        department_id: uuid.UUID | None,
        duty: str | None,
        report_to_id: uuid.UUID | None,
    ) -> None:
        """Normalize mutable template fields without overwriting an existing prompt."""
        validate_model_role(model_role)
        validate_tier(tier)
        self.code = code
        self.name = name
        self.title = title
        self.tier = tier
        self.model_role = model_role
        self.department_id = department_id
        self.is_seed = True
        if not self.duty:
            self.duty = duty
        if report_to_id is not None:
            self.report_to_id = report_to_id

    def delete(self) -> None:
        self.is_deleted = True
