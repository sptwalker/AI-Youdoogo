"""Published, framework-independent Environment Projection snapshot contract."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime


def _require_aware(value: datetime, *, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must include a timezone")


@dataclass(frozen=True, slots=True)
class SnapshotScope:
    """Tenant and named source areas represented by a composed snapshot."""

    tenant_id: str
    areas: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.tenant_id:
            raise ValueError("snapshot tenant_id is required")
        if not self.areas or any(not area for area in self.areas):
            raise ValueError("snapshot scope requires named areas")
        if len(set(self.areas)) != len(self.areas):
            raise ValueError("snapshot scope areas must be unique")


@dataclass(frozen=True, slots=True)
class SnapshotProvenance:
    """Evidence describing the source event observed by the projection."""

    event_id: uuid.UUID
    source_type: str
    source_id: uuid.UUID
    observed_at: datetime

    def __post_init__(self) -> None:
        if not self.source_type:
            raise ValueError("snapshot provenance source_type is required")
        _require_aware(self.observed_at, field="observed_at")


@dataclass(frozen=True, slots=True)
class SnapshotSourceVersion:
    """Monotonic revision included for one source-owned fact."""

    source_type: str
    source_id: uuid.UUID
    version: int

    def __post_init__(self) -> None:
        if not self.source_type:
            raise ValueError("snapshot source_type is required")
        if self.version <= 0:
            raise ValueError("snapshot source version must be positive")


@dataclass(frozen=True, slots=True)
class MissingSnapshotSource:
    """A source area that could not be represented safely in the snapshot."""

    source_type: str
    reason: str
    required: bool = True

    def __post_init__(self) -> None:
        if not self.source_type or not self.reason:
            raise ValueError("missing snapshot source requires type and reason")


@dataclass(frozen=True, slots=True)
class ContextSnapshot:
    """Immutable Environment Projection result consumed across Context boundaries."""

    scope: SnapshotScope
    content: str
    provenance: tuple[SnapshotProvenance, ...]
    source_versions: tuple[SnapshotSourceVersion, ...]
    missing: tuple[MissingSnapshotSource, ...]
    stale: bool
    generated_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        _require_aware(self.generated_at, field="generated_at")
        _require_aware(self.expires_at, field="expires_at")
        if self.expires_at < self.generated_at:
            raise ValueError("snapshot expiry cannot precede generation")
        version_keys = {
            (item.source_type, item.source_id) for item in self.source_versions
        }
        if len(version_keys) != len(self.source_versions):
            raise ValueError("snapshot source versions must be unique")

    def is_expired(self, at: datetime | None = None) -> bool:
        moment = at or datetime.now(UTC)
        _require_aware(moment, field="at")
        return moment >= self.expires_at

    def is_usable(self, at: datetime | None = None) -> bool:
        """Fail closed when the projection is stale, expired, or missing required data."""
        return (
            not self.stale
            and not self.is_expired(at)
            and not any(item.required for item in self.missing)
        )
