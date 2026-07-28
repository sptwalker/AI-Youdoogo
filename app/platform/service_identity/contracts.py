"""Plain contracts for authenticated internal service calls."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class ServiceIdentityClaims:
    """Verified identity and delegation context carried between services."""

    issuer: str
    audience: str
    service_id: str
    actor: str
    scope: tuple[str, ...]
    issued_at: datetime
    expires_at: datetime
    jti: str

    def permits(self, required_scopes: tuple[str, ...]) -> bool:
        """Return whether every required scope is granted by the token."""
        granted = set(self.scope)
        return all(scope in granted for scope in required_scopes)
