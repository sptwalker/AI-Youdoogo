"""Organization Structure commands."""

from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CreateDepartmentCommand:
    name: str
    parent_id: uuid.UUID
    code: str | None = None


@dataclass(frozen=True, slots=True)
class UpdateDepartmentCommand:
    department_id: uuid.UUID
    name: str | None = None
    sort_order: int | None = None


@dataclass(frozen=True, slots=True)
class SetSupervisorCommand:
    department_id: uuid.UUID
    supervisor_user_id: uuid.UUID | None


@dataclass(frozen=True, slots=True)
class SeedOrganizationTemplateCommand:
    ceo_user_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class OrganizationTemplateResult:
    root: str
    departments: int
    execs: int
    directors: int

    def as_dict(self) -> dict[str, object]:
        return {
            "root": self.root,
            "departments": self.departments,
            "execs": self.execs,
            "directors": self.directors,
        }


@dataclass(frozen=True, slots=True)
class ExternalDepartmentRecord:
    external_id: str
    parent_external_id: str | None
    name: str


@dataclass(frozen=True, slots=True)
class ExternalUserRecord:
    external_id: str
    name: str
    department_external_ids: tuple[str, ...]
    en_name: str = ""
    title: str = ""
    mobile: str = ""
    avatar_url: str = ""


@dataclass(frozen=True, slots=True)
class OrganizationDirectorySyncResult:
    departments: int
    users_created: int
    users_updated: int

    def as_dict(self) -> dict[str, int]:
        return {
            "departments": self.departments,
            "users_created": self.users_created,
            "users_updated": self.users_updated,
        }


@dataclass(frozen=True, slots=True)
class TemplateExpertSpec:
    code: str
    name: str
    title: str
    tier: str
    model_role: str
    department_id: uuid.UUID
    prompt_template: str
    duty: str | None = None
    report_to_id: uuid.UUID | None = None
