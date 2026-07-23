"""Pure System Configuration commands and views."""

from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ConfigView:
    config_id: uuid.UUID
    key: str
    value: object
    value_type: str
    category: str
    is_editable: bool
    is_secret: bool
    is_set: bool


@dataclass(frozen=True, slots=True)
class UpdateConfigCommand:
    key: str
    value: object
    updated_by: uuid.UUID | None
    actor_role: str | None
