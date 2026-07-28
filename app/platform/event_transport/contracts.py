"""Transport-neutral contracts for future at-least-once cross-service delivery."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Self

type JSONScalar = str | int | float | bool | None
type JSONValue = JSONScalar | list[JSONValue] | dict[str, JSONValue]


def _aware(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value


def _required(value: str, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    return normalized


@dataclass(frozen=True, slots=True)
class EventEnvelope:
    """Stable event metadata plus a versioned JSON payload."""

    event_id: str
    event_type: str
    schema_version: int
    occurred_at: datetime
    producer: str
    payload: dict[str, JSONValue]
    correlation_id: str | None = None
    causation_id: str | None = None
    headers: Mapping[str, str] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_id", _required(self.event_id, "event_id"))
        object.__setattr__(self, "event_type", _required(self.event_type, "event_type"))
        object.__setattr__(self, "producer", _required(self.producer, "producer"))
        if self.schema_version < 1:
            raise ValueError("schema_version must be at least 1")
        _aware(self.occurred_at, "occurred_at")
        if self.correlation_id is not None:
            object.__setattr__(
                self,
                "correlation_id",
                _required(self.correlation_id, "correlation_id"),
            )
        if self.causation_id is not None:
            object.__setattr__(self, "causation_id", _required(self.causation_id, "causation_id"))
        if self.headers is not None:
            normalized_headers = {
                _required(key, "header name"): _required(value, "header value")
                for key, value in self.headers.items()
            }
            object.__setattr__(self, "headers", MappingProxyType(normalized_headers))

    @classmethod
    def new(
        cls,
        *,
        event_type: str,
        producer: str,
        payload: dict[str, JSONValue],
        schema_version: int = 1,
        occurred_at: datetime | None = None,
        event_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> Self:
        """Create an envelope at the call site; adapters only transport it."""
        return cls(
            event_id=event_id or str(uuid.uuid4()),
            event_type=event_type,
            schema_version=schema_version,
            occurred_at=occurred_at or datetime.now(UTC),
            producer=producer,
            payload=payload,
            correlation_id=correlation_id,
            causation_id=causation_id,
            headers=headers,
        )


@dataclass(frozen=True, slots=True)
class InboxClaim:
    """Lease token proving one consumer currently owns an event attempt."""

    event_id: str
    consumer_id: str
    claim_id: str
    attempt: int
    claimed_at: datetime
    lease_until: datetime

    def __post_init__(self) -> None:
        for field in ("event_id", "consumer_id", "claim_id"):
            object.__setattr__(self, field, _required(getattr(self, field), field))
        _aware(self.claimed_at, "claimed_at")
        _aware(self.lease_until, "lease_until")
        if self.attempt < 1:
            raise ValueError("attempt must be at least 1")
        if self.lease_until <= self.claimed_at:
            raise ValueError("lease_until must be later than claimed_at")


@dataclass(frozen=True, slots=True)
class DeliveryFailure:
    """Failure evidence used for retry decisions and eventual dead lettering."""

    failure_id: str
    envelope: EventEnvelope
    consumer_id: str
    attempt: int
    failed_at: datetime
    error_code: str
    error_message: str
    retryable: bool
    retry_at: datetime | None = None

    def __post_init__(self) -> None:
        for field in ("failure_id", "consumer_id", "error_code", "error_message"):
            object.__setattr__(self, field, _required(getattr(self, field), field))
        if self.attempt < 1:
            raise ValueError("attempt must be at least 1")
        _aware(self.failed_at, "failed_at")
        if self.retry_at is not None:
            _aware(self.retry_at, "retry_at")
            if self.retry_at <= self.failed_at:
                raise ValueError("retry_at must be later than failed_at")
            if not self.retryable:
                raise ValueError("non-retryable failures cannot schedule retry_at")

    @classmethod
    def new(
        cls,
        *,
        envelope: EventEnvelope,
        consumer_id: str,
        attempt: int,
        error_code: str,
        error_message: str,
        retryable: bool,
        failed_at: datetime | None = None,
        retry_at: datetime | None = None,
    ) -> Self:
        """Create immutable failure evidence with a unique failure identifier."""
        return cls(
            failure_id=str(uuid.uuid4()),
            envelope=envelope,
            consumer_id=consumer_id,
            attempt=attempt,
            failed_at=failed_at or datetime.now(UTC),
            error_code=error_code,
            error_message=error_message,
            retryable=retryable,
            retry_at=retry_at,
        )


@dataclass(frozen=True, slots=True)
class DeadLetterRecord:
    """Terminal delivery failure retained for audit and controlled replay."""

    dead_letter_id: str
    failure: DeliveryFailure
    stored_at: datetime
    replay_count: int = 0
    last_replayed_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "dead_letter_id",
            _required(self.dead_letter_id, "dead_letter_id"),
        )
        _aware(self.stored_at, "stored_at")
        if self.replay_count < 0:
            raise ValueError("replay_count must not be negative")
        if self.last_replayed_at is not None:
            _aware(self.last_replayed_at, "last_replayed_at")

    def mark_replayed(self, replayed_at: datetime) -> Self:
        """Return the next immutable replay state."""
        _aware(replayed_at, "replayed_at")
        return replace(
            self,
            replay_count=self.replay_count + 1,
            last_replayed_at=replayed_at,
        )


@dataclass(frozen=True, slots=True)
class ReplayRequest:
    """Auditable operator intent to redeliver a dead-lettered event."""

    request_id: str
    dead_letter_id: str
    requested_by: str
    requested_at: datetime
    reason: str

    def __post_init__(self) -> None:
        for field in ("request_id", "dead_letter_id", "requested_by", "reason"):
            object.__setattr__(self, field, _required(getattr(self, field), field))
        _aware(self.requested_at, "requested_at")

    @classmethod
    def new(
        cls,
        *,
        dead_letter_id: str,
        requested_by: str,
        reason: str,
        requested_at: datetime | None = None,
    ) -> Self:
        """Create a replay command; replay retains the original event identifier."""
        return cls(
            request_id=str(uuid.uuid4()),
            dead_letter_id=dead_letter_id,
            requested_by=requested_by,
            requested_at=requested_at or datetime.now(UTC),
            reason=reason,
        )
