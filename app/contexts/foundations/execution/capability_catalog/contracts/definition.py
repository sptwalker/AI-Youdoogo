"""Versioned capability metadata without runtime handlers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class CapabilityRisk(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class CapabilitySideEffect(StrEnum):
    NONE = "none"
    INTERNAL_WRITE = "internal_write"
    EXTERNAL_WRITE = "external_write"


@dataclass(frozen=True, slots=True)
class CapabilityDefinition:
    key: str
    version: str
    label: str
    description: str
    input_schema_json: str
    output_schema_json: str
    risk: CapabilityRisk
    side_effect: CapabilitySideEffect
    permission_keys: tuple[str, ...]
    handler_identity: str
    feature_flag: str | None = None
    default_enabled: bool = True
