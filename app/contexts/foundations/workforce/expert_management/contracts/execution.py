"""Immutable expert configuration consumed by execution contexts."""

from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ExpertExecutionSnapshot:
    """Versioned expert facts needed to reproduce one execution."""

    expert_id: uuid.UUID
    version: str
    name: str
    title: str
    department_id: uuid.UUID | None
    prompt_template: str
    model_role: str
    capability_keys: tuple[str, ...] = ()
    permission_entries: tuple[tuple[str, str], ...] = ()
    owner_user_id: uuid.UUID | None = None
