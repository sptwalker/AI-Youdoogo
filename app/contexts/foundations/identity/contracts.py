"""Published, framework-independent Identity contracts."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import StrEnum


class PrincipalType(StrEnum):
    """Kinds of authenticated actors recognized by the platform."""

    USER = "user"
    AGENT = "agent"


@dataclass(frozen=True, slots=True)
class Principal:
    """Stable caller identity passed to policy and business use cases."""

    principal_type: PrincipalType
    principal_id: uuid.UUID
    role_code: str
    department_id: uuid.UUID | None
    is_active: bool = True
