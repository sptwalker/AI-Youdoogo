"""Pure capability invocation request, result, and trace."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import StrEnum


class CapabilityExecutionStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class CapabilityPrincipal:
    principal_id: uuid.UUID | None
    expert_id: uuid.UUID
    permission_keys: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CapabilityTrace:
    trace_id: uuid.UUID | None = None
    workflow_run_id: uuid.UUID | None = None
    workflow_step_id: uuid.UUID | None = None
    attempt: int | None = None


@dataclass(frozen=True, slots=True)
class CapabilityExecutionRequest:
    capability_key: str
    action_index: int
    arguments_json: str
    principal: CapabilityPrincipal
    trace: CapabilityTrace = CapabilityTrace()
    capability_version: str | None = None
    idempotency_key: str | None = None
    approval_reference: str | None = None
    raw_text: str | None = None


@dataclass(frozen=True, slots=True)
class CapabilityEvidence:
    kind: str
    reference: str


@dataclass(frozen=True, slots=True)
class CapabilityExecutionError:
    code: str
    message: str
    retryable: bool = False


@dataclass(frozen=True, slots=True)
class CapabilityExecutionResult:
    status: CapabilityExecutionStatus
    capability_key: str
    capability_version: str
    invocation_id: uuid.UUID | None = None
    output_json: str = "{}"
    notes: tuple[str, ...] = ()
    dataset_json: tuple[str, ...] = ()
    artifact_json: tuple[str, ...] = ()
    evidence: tuple[CapabilityEvidence, ...] = ()
    audit_correlation_id: uuid.UUID | None = None
    replayed: bool = False
    error: CapabilityExecutionError | None = None
