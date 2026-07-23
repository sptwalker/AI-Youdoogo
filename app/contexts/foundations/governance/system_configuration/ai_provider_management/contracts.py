"""Published AI Provider commands and safe result values."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class ProviderActor:
    actor_id: uuid.UUID | None
    role_code: str | None


@dataclass(frozen=True, slots=True)
class CreateProviderCommand:
    name: str
    tier: str
    base_url: str
    api_key: str
    model: str
    actor: ProviderActor | None = None


@dataclass(frozen=True, slots=True)
class UpdateProviderCommand:
    provider_id: uuid.UUID
    name: str | None = None
    tier: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None
    actor: ProviderActor | None = None


@dataclass(frozen=True, slots=True)
class ProviderSnapshot:
    provider_id: uuid.UUID
    name: str
    tier: str
    base_url: str
    model: str
    api_key_hint: str
    api_key_set: bool
    is_primary: bool
    is_active: bool
    last_test_status: str
    last_test_at: datetime | None
    last_test_latency_ms: int | None
    last_test_message: str | None

    @property
    def id(self) -> uuid.UUID:
        """Compatibility alias for callers that previously received an ORM row."""
        return self.provider_id

    def to_dict(self) -> dict[str, object]:
        return {
            "id": str(self.provider_id),
            "name": self.name,
            "tier": self.tier,
            "base_url": self.base_url,
            "model": self.model,
            "api_key_hint": self.api_key_hint,
            "api_key_set": self.api_key_set,
            "is_primary": self.is_primary,
            "is_active": self.is_active,
            "last_test_status": self.last_test_status,
            "last_test_at": (
                self.last_test_at.isoformat() if self.last_test_at else None
            ),
            "last_test_latency_ms": self.last_test_latency_ms,
            "last_test_msg": self.last_test_message,
        }


@dataclass(frozen=True, slots=True)
class ProviderTestResult:
    status: str
    latency_ms: int | None
    message: str

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "latency_ms": self.latency_ms,
            "msg": self.message,
        }


@dataclass(frozen=True, slots=True)
class ProviderTestSummary:
    provider_id: uuid.UUID
    result: ProviderTestResult

    def to_dict(self) -> dict[str, object]:
        return {"id": str(self.provider_id), **self.result.to_dict()}
