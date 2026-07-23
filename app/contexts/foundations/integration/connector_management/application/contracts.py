"""Connector Management commands."""

from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RegisterConnector:
    name: str
    connector_type: str
    code: str | None = None
    department_id: uuid.UUID | None = None
    config: dict[str, object] | None = None
    secret_ref: str | None = None
    owner_expert_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class UpdateConnector:
    connector_id: uuid.UUID
    name: str | None = None
    config: dict[str, object] | None = None
    secret_ref: str | None = None
    is_active: bool | None = None
    department_id: uuid.UUID | None = None
    owner_expert_id: uuid.UUID | None = None
