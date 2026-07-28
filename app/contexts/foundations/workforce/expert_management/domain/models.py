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
class OrgExpertMember:
    """Organizational membership and lifecycle state for one expert."""

    code: str | None
    name: str
    title: str
    tier: str
    department_id: uuid.UUID | None
    report_to_id: uuid.UUID | None
    owner_user_id: uuid.UUID | None
    is_seed: bool
    is_active: bool
    is_deleted: bool = False

    def revise(
        self,
        *,
        name: str | None,
        title: str | None,
        tier: str | None,
        report_to_id: uuid.UUID | None,
        department_id: uuid.UUID | None,
        is_active: bool | None,
    ) -> None:
        if tier is not None:
            validate_tier(tier)
            self.tier = tier
        if name is not None:
            self.name = name
        if title is not None:
            self.title = title
        if is_active is not None:
            self.is_active = is_active
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
        department_id: uuid.UUID | None,
        report_to_id: uuid.UUID | None,
    ) -> None:
        """Normalize stable template identity fields."""
        validate_tier(tier)
        self.code = code
        self.name = name
        self.title = title
        self.tier = tier
        self.department_id = department_id
        self.is_seed = True
        if report_to_id is not None:
            self.report_to_id = report_to_id

    def delete(self) -> None:
        self.is_deleted = True


@dataclass(slots=True)
class ExpertExecutionDefinition:
    """Prompt, model and capability configuration for expert execution."""

    prompt_template: str
    model_role: str
    permission_scope_json: str
    tools_json: str
    duty: str | None

    def revise(
        self,
        *,
        prompt_template: str | None,
        model_role: str | None,
        permission_scope_json: str | None,
        tools_json: str | None,
        duty: str | None,
    ) -> None:
        if model_role is not None:
            validate_model_role(model_role)
            self.model_role = model_role
        if prompt_template:
            self.prompt_template = prompt_template
        if duty is not None:
            self.duty = duty
        if permission_scope_json is not None:
            self.permission_scope_json = permission_scope_json
        if tools_json is not None:
            self.tools_json = tools_json

    def apply_seed(self, *, model_role: str, duty: str | None) -> None:
        validate_model_role(model_role)
        self.model_role = model_role
        if not self.duty:
            self.duty = duty


@dataclass(slots=True)
class ExpertProfile:
    """Composition root for independent membership and execution definitions."""

    id: uuid.UUID
    version: str
    create_time: datetime
    member: OrgExpertMember
    execution: ExpertExecutionDefinition

    @property
    def is_deleted(self) -> bool:
        return self.member.is_deleted

    def delete(self) -> None:
        self.member.delete()
