"""Capability-owned catalog, policy, invocation, and handler ports."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol

from app.contexts.foundations.execution.capability_catalog.contracts.definition import (
    CapabilityDefinition,
)
from app.contexts.foundations.execution.capability_execution.contracts.execution import (
    CapabilityEvidence,
    CapabilityExecutionRequest,
    CapabilityExecutionResult,
)


@dataclass(frozen=True, slots=True)
class AuthorizationDecision:
    allowed: bool
    reason: str = ""


@dataclass(frozen=True, slots=True)
class ApprovalDecision:
    approved: bool
    reason: str = ""


@dataclass(frozen=True, slots=True)
class InvocationClaim:
    invocation_id: uuid.UUID
    replay_result: CapabilityExecutionResult | None = None


@dataclass(frozen=True, slots=True)
class HandlerExecutionResult:
    output_json: str = "{}"
    notes: tuple[str, ...] = ()
    dataset_json: tuple[str, ...] = ()
    artifact_json: tuple[str, ...] = ()
    evidence: tuple[CapabilityEvidence, ...] = ()


class CapabilityCatalogPort(Protocol):
    async def resolve(self, key: str, version: str | None) -> CapabilityDefinition | None: ...


class CapabilityAuthorizationPort(Protocol):
    async def authorize(
        self, request: CapabilityExecutionRequest, definition: CapabilityDefinition
    ) -> AuthorizationDecision: ...


class CapabilityApprovalPort(Protocol):
    async def check(
        self, request: CapabilityExecutionRequest, definition: CapabilityDefinition
    ) -> ApprovalDecision: ...


class CapabilityInvocationPort(Protocol):
    async def claim(self, request: CapabilityExecutionRequest) -> InvocationClaim: ...

    async def succeed(
        self, invocation_id: uuid.UUID, result: CapabilityExecutionResult
    ) -> None: ...

    async def fail(self, invocation_id: uuid.UUID, error_message: str) -> None: ...


class CapabilityExecutionUnitOfWork(Protocol):
    @property
    def invocations(self) -> CapabilityInvocationPort: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


class CapabilityHandlerPort(Protocol):
    async def execute(
        self, request: CapabilityExecutionRequest, definition: CapabilityDefinition
    ) -> HandlerExecutionResult: ...
