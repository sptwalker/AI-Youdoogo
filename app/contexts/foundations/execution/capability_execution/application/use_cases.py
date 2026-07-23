"""Validation, policy, idempotency, dispatch, and normalization for capabilities."""

from __future__ import annotations

import json
import uuid
from dataclasses import replace

from app.contexts.foundations.execution.capability_execution.application.ports import (
    CapabilityApprovalPort,
    CapabilityAuthorizationPort,
    CapabilityCatalogPort,
    CapabilityExecutionUnitOfWork,
    CapabilityHandlerPort,
)
from app.contexts.foundations.execution.capability_execution.contracts.execution import (
    CapabilityExecutionError,
    CapabilityExecutionRequest,
    CapabilityExecutionResult,
    CapabilityExecutionStatus,
)


class CapabilityExecutionApplication:
    def __init__(
        self,
        *,
        catalog: CapabilityCatalogPort,
        authorization: CapabilityAuthorizationPort,
        approval: CapabilityApprovalPort,
        uow: CapabilityExecutionUnitOfWork,
        handler: CapabilityHandlerPort,
    ) -> None:
        self._catalog = catalog
        self._authorization = authorization
        self._approval = approval
        self._uow = uow
        self._handler = handler

    async def execute(self, request: CapabilityExecutionRequest) -> CapabilityExecutionResult:
        definition = await self._catalog.resolve(
            request.capability_key, request.capability_version
        )
        if definition is None:
            return self._rejected(request, "not_registered", "能力未注册或版本不匹配")
        if not self._valid_arguments(request.arguments_json):
            return self._rejected(request, "invalid_arguments", "能力参数必须是 JSON 对象")

        authorization = await self._authorization.authorize(request, definition)
        if not authorization.allowed:
            return self._rejected(
                request, "not_authorized", authorization.reason or "能力调用未获授权"
            )
        approval = await self._approval.check(request, definition)
        if not approval.approved:
            return self._rejected(
                request, "approval_required", approval.reason or "能力调用需要真人审批"
            )

        invocation_id: uuid.UUID | None = None
        if request.idempotency_key is not None:
            claim = await self._uow.invocations.claim(request)
            invocation_id = claim.invocation_id
            if claim.replay_result is not None:
                return replace(
                    claim.replay_result,
                    invocation_id=invocation_id,
                    replayed=True,
                )
            await self._uow.commit()

        try:
            handled = await self._handler.execute(request, definition)
        except Exception as exc:  # noqa: BLE001 - normalize adapter failures
            if invocation_id is not None:
                await self._uow.invocations.fail(invocation_id, str(exc))
                await self._uow.commit()
            return CapabilityExecutionResult(
                status=CapabilityExecutionStatus.FAILED,
                capability_key=definition.key,
                capability_version=definition.version,
                invocation_id=invocation_id,
                audit_correlation_id=request.trace.trace_id,
                error=CapabilityExecutionError(code="execution_failed", message=str(exc)),
            )

        result = CapabilityExecutionResult(
            status=CapabilityExecutionStatus.SUCCEEDED,
            capability_key=definition.key,
            capability_version=definition.version,
            invocation_id=invocation_id,
            output_json=handled.output_json,
            notes=handled.notes,
            dataset_json=handled.dataset_json,
            artifact_json=handled.artifact_json,
            evidence=handled.evidence,
            audit_correlation_id=request.trace.trace_id or uuid.uuid4(),
        )
        if invocation_id is not None:
            await self._uow.invocations.succeed(invocation_id, result)
            await self._uow.commit()
        return result

    @staticmethod
    def _valid_arguments(arguments_json: str) -> bool:
        try:
            return isinstance(json.loads(arguments_json), dict)
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _rejected(
        request: CapabilityExecutionRequest, code: str, message: str
    ) -> CapabilityExecutionResult:
        return CapabilityExecutionResult(
            status=CapabilityExecutionStatus.REJECTED,
            capability_key=request.capability_key,
            capability_version=request.capability_version or "",
            audit_correlation_id=request.trace.trace_id,
            error=CapabilityExecutionError(code=code, message=message),
        )
