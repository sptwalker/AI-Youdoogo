"""AI Provider state and invariants independent from persistence and LLM SDKs."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from app.contexts.shared_kernel import RuleViolation

TIER_DAILY = "daily"
TIER_REASONING = "reasoning"
VALID_TIERS = (TIER_DAILY, TIER_REASONING)


def validate_tier(tier: str) -> None:
    if tier not in VALID_TIERS:
        raise RuleViolation(f"tier 仅支持 {'/'.join(VALID_TIERS)}")


def secret_hint(api_key: str) -> str:
    key = (api_key or "").strip()
    if not key:
        return ""
    return f"****{key[-4:]}" if len(key) >= 4 else "****"


@dataclass(slots=True)
class ProviderRecord:
    id: uuid.UUID
    name: str
    tier: str
    base_url: str
    api_key: str
    api_key_hint: str
    model: str
    is_primary: bool
    is_active: bool
    create_time: datetime
    last_test_status: str = "untested"
    last_test_at: datetime | None = None
    last_test_latency_ms: int | None = None
    last_test_message: str | None = None
    is_deleted: bool = False

    def update(
        self,
        *,
        name: str | None,
        tier: str | None,
        base_url: str | None,
        api_key: str | None,
        model: str | None,
    ) -> None:
        if name is not None:
            self.name = name
        if tier is not None:
            validate_tier(tier)
            self.tier = tier
        if base_url is not None:
            self.base_url = base_url.strip()
        if model is not None:
            self.model = model.strip()
        if api_key:
            self.api_key = api_key.strip()
            self.api_key_hint = secret_hint(api_key)

    def mark_deleted(self) -> None:
        self.is_deleted = True
        self.is_primary = False

    def set_active(self, active: bool) -> None:
        self.is_active = active
        if not active:
            self.is_primary = False

    def make_primary(self) -> None:
        if not self.is_active:
            raise RuleViolation("禁用中的卡片不能设为主用，请先启用")
        self.is_primary = True

    def record_test(
        self,
        *,
        status: str,
        latency_ms: int | None,
        message: str,
        tested_at: datetime,
    ) -> None:
        self.last_test_status = status
        self.last_test_latency_ms = latency_ms
        self.last_test_message = message[:256]
        self.last_test_at = tested_at
