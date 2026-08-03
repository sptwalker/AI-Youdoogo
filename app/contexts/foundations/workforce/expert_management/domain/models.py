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


@dataclass(frozen=True, slots=True)
class ExpertRelease:
    """不可变执行发布快照（Module 2 / docs/23 §4.2）——发布时冻结 execution 定义，只增不改。"""

    id: uuid.UUID
    expert_id: uuid.UUID
    version_no: int
    prompt_template: str
    model_role: str
    permission_scope_json: str
    tools_json: str
    duty: str | None
    released_by: uuid.UUID | None
    released_at: datetime
    eval_score: float | None = None
    eval_case_count: int | None = None

    @classmethod
    def cut(
        cls,
        *,
        release_id: uuid.UUID,
        expert: ExpertProfile,
        version_no: int,
        released_by: uuid.UUID | None,
        released_at: datetime,
        eval_score: float | None = None,
        eval_case_count: int | None = None,
    ) -> ExpertRelease:
        """把某专家当前执行定义冻结成一版发布快照（可附评测证据，Module 3）。"""
        ex = expert.execution
        return cls(
            id=release_id,
            expert_id=expert.id,
            version_no=version_no,
            prompt_template=ex.prompt_template,
            model_role=ex.model_role,
            permission_scope_json=ex.permission_scope_json,
            tools_json=ex.tools_json,
            duty=ex.duty,
            released_by=released_by,
            released_at=released_at,
            eval_score=eval_score,
            eval_case_count=eval_case_count,
        )
