"""Typed, role-free principal returned by a verified Lodge user target token."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class LodgePrincipal:
    """Identity facts only; decisions about local roles remain in Youdoogo ACLs."""

    subject: str
    session_id: str
    organization_id: str
    identity_version: int
    token_id: str
    issued_at: datetime
    expires_at: datetime
